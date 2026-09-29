# DSO Practice Integration API — Product Requirements Document

## 1. Introduction

A dental support organization buys practices, not dentistry. That single sentence is the reason this system exists and the reason it is hard to build. When the support organization acquires a selling dental group, it takes on the purchase price, the earn-out, the practice-management-system conversion, the payer contracts, the supply catalogue and the staffing model — but it may never take on clinical judgement, which by law remains with licensed dentists. Every workflow in this API therefore runs along two tracks at once: a commercial track that the support organization's own operators drive, and a clinical track that only a locally licensed clinician may touch. Mixing the two is not a warning; it is a rejected request.

The API is mounted under `/dso` and covers the whole affiliation arc. Deal counsel opens a transaction file against a target group, attaches the practices being bought, moves the file through diligence — sometimes repricing it and looping back to drafting — and signs. An integration lead then closes the transaction, which triggers a wide, transitive cascade: practices become affiliated, accepted employment offers activate, unaccepted offers lapse, credentialing enrollments spring into existence for every legacy payer contract, and those contracts move into a pending-credentialing posture. From that moment the integration lead is converting charts inside vendor-constrained cutover windows, the finance controller is transitioning fee schedules and harmonizing compensation, the clinical director is reviewing charts and adjudicating formulary exceptions, and the earn-out pool is being reserved and settled by two different finance users who are forbidden from being the same person.

The hardest requirement in this document is not any single rule but the way the rules interlock. A practice's **integration posture** is never written by a client; it is derived from five counters that unrelated child workflows maintain, and it gates almost every integration operation. A doctor's departure can freeze a practice, hold its migration batches, suspend its credentialing, revert its payer contracts and suspend earn-out measurement — five hops from one call. Two conserved-quantity ledgers, one over earn-out cents and one over migrated chart records, must balance exactly after every write, including after compensating operations that undo earlier ones. Implementers should read §2 as a contract and §3 as the business narrative from which the workflow logic must be reconstructed.

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors, Identity Headers and Clinical Authority

Every request to every endpoint must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` before any resource is looked up. Five roles exist and their spellings are exact: `DsoDealCounsel`, `DsoIntegrationLead`, `DsoFinanceController`, `ClinicalDirector`, and `Dentist`. A role value outside that set, or a recognized role that is not authorized for the endpoint being called, is rejected with `ERR_UNAUTHORIZED`. The role gate is evaluated before existence checks, so an unauthorized caller can never learn which identifiers exist by observing a 404.

`DsoDealCounsel`, `DsoIntegrationLead` and `DsoFinanceController` are **opaque** identities. When `X-User-Role` is `DsoDealCounsel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the same is true when `X-User-Role` is `DsoIntegrationLead`, and again when it is `DsoFinanceController`. The server may record such an identifier — it stores it as `reserved_by_user_id` and later as `settled_by_user_id` on an earn-out tranche, and it compares those two recorded values to each other — but it never compares an opaque identifier to any entity's `id`.

`ClinicalDirector` and `Dentist` are **entity-backed** identities. When `X-User-Role` is `ClinicalDirector`, `X-User-ID` is the `id` of the acting `Doctor`; that resolved doctor record is what the licensure and self-review checks of §2.12 read — its `license_state` against the practice's `state_code`, and its `id` against the reviewed employment's `doctor_id` — and the director's identity is stamped onto decisions as `decided_by_doctor_id` or `closed_by_doctor_id`. No endpoint imposes an *ownership* precondition on an entity-backed caller: `X-User-ID` is never required to equal a resource's doctor foreign key, so any dentist whose identifier resolves to a `Doctor` may accept, separate against, or request a preference exception for any employment row whatever, and the only comparison of the two anywhere is the self-review prohibition, which forbids the match rather than requiring it. When `X-User-Role` is `Dentist`, `X-User-ID` is likewise the `id` of the acting `Doctor`. For both entity-backed roles, an `X-User-ID` that does not resolve to an existing `Doctor` row cannot act as a clinician and the request is rejected with `ERR_UNAUTHORIZED`. This resolution check is applied on exactly seven operations: accepting an employment offer, separating an employment, transferring records custody, requesting a supply preference exception, deciding a supply preference exception, opening a clinical quality review, and closing a clinical quality review.

Authority is deliberately partitioned. Deal counsel owns the affiliation file, the repricing and signing decisions, the non-clinical service agreement and its scope, and restrictive-covenant enforcement. The integration lead owns closing, conversion vendors, chart migration, credentialing enrollments, staffing standardization, vendor consolidation and employment offers. The finance controller owns payer contracts, fee schedules, compensation harmonization and the earn-out tranche lifecycle. The clinical director owns clinical quality determinations, formulary exception decisions and post-departure records custody. A dentist accepts or declines employment terms, may resign, and may request formulary exceptions. Every role may drive the logical clock.

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

### 2.3. Pagination and List Ordering

Collection reads accept two query parameters. `limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100. `offset` skips rows from the front of the result set; it defaults to 0 and may not be negative. A `limit` outside the inclusive range 1 through 100, or a negative `offset`, is a payload-shape failure and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order, with rows that share an identical `created_at` — the common case, since the logical clock only advances when a client advances it — ordered by creation sequence, earliest-created first. List responses carry `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object; `total_count` counts the rows matching the filter before pagination is applied, and `has_more` is true when rows remain beyond the current page.

Filters, where offered, are exact-match on a single field. Affiliations may be filtered by `status`. Practices may be filtered by `affiliation_id`, by `conversion_vendor_id` or by `integration_posture`. Employment rows may be filtered by `practice_id`, `doctor_id` or `employment_status`. Service agreements accept `practice_id` and `status`; migration batches accept `practice_id` and `status`; payer contracts accept `practice_id` and `transition_state`; payer enrollments accept `payer_contract_id`, `doctor_employment_id` and `status`; earn-out tranches accept `affiliation_id` and `status`. Of the five sub-resource readers, only an employment's preference exceptions and an employment's quality reviews accept a `status` filter; a practice's consolidations, an agreement's line items and a contract's fee schedule items accept the two pagination parameters and nothing more. All five paginate exactly like a top-level collection. A filter value that is well formed but names no declared enum member, or an identifier that matches no row, is never rejected — it simply selects nothing and yields an empty page with `total_count` zero.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource — affiliations, conversion vendors, practices, doctors, doctor employments, service agreements, migration batches, payer contracts, payer enrollments, earn-out tranches, supply preference exceptions, vendor consolidations and clinical quality reviews — carries four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the row, including mutations that only change a derived counter or a derived enum; on a freshly created row it equals that row's `created_at` exactly.
- `version` (integer): an integer that stands at 1 on a freshly created row and increments by one on every mutation of the row.

Two resources are exceptions. A **service line item** on a management services agreement and a **fee schedule item** on a payer contract each carry only `id` and `created_at`. Both `updated_at` and `version` are absent from those two resources entirely; they are written once and never mutated.

All time in this system comes from a **logical clock**, never from wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. Any role may advance it by supplying a `current_utc` instant; the clock may move forward or stay where it is, but a requested value earlier than the current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` and an equal value is accepted as a no-op. Every timestamp the server stamps — `diligence_opened_at`, `signed_date`, `close_date`, `effective_date` on an agreement, `comp_effective_date`, `separation_date`, `submitted_at`, `decided_at` — is read from the logical clock, as are every lead-time computation, every annualization denominator and every cutover-window comparison.

**Business date-time** values are serialized back to clients in the same whole-second form this document writes them in — `2026-08-01T00:00:00Z`, `9999-12-31T00:00:00Z` — rather than in the three-fractional-digit form. The business date-time fields are `diligence_opened_at`, `signed_date` and `close_date` on an affiliation; `comp_effective_date`, `non_compete_end_date` and `separation_date` on an employment; `effective_date` on an agreement; `cutover_start_at` and `cutover_end_at` on a migration batch; `dso_schedule_effective_date` on a payer contract; `effective_date`, `term_date`, `submitted_at` and `decided_at` on an enrollment; and `measurement_start` and `measurement_end` on an earn-out tranche. Each of them renders with no fractional digits whenever it falls on a whole second, which is the form the logical clock's own instants take and the form in which a whole-second client-supplied window, participation date or measurement bound is echoed back. Only a value carrying a genuine sub-second component falls back to three fractional digits. The three-fractional-digit form remains mandatory for the envelope's `api_request_timestamp` and for `created_at` and `updated_at` on every resource that carries them, whatever the underlying instant.

### 2.5. Money, Basis Points and Rounding Discipline

Money in this system is always an integer count of cents; there are no decimal currency values anywhere in the API. Rates, ratios and scores are always integer **basis points**, where ten thousand basis points equal one hundred percent. Because both representations are integral, the only place precision can be lost is at a division, and every division in this document is performed as exact rational arithmetic followed by exactly one rounding step at the point where a rounding instruction is written. No other step rounds.

The single rounding method is **round half up, half away from zero**: a positive value with a fractional part of exactly one half rounds up in magnitude, and a negative value with a fractional part of exactly one half rounds down (that is, further from zero). This matters because several figures in this system are legitimately negative — a fee-schedule transition can erode collections, and an earn-out can measure below its baseline.

Two fiscal ceilings are enforced at the moment a commitment becomes real rather than at the moment it is drafted. A management services agreement may carry any non-negative `mgmt_fee_bps` while it is being drafted and reviewed, but at the moment it would become effective the fee is capped at 2,000 basis points — twenty percent of collections — and exactly 2,000 is allowed while 2,001 is rejected with `ERR_MGMT_FEE_CAP_EXCEEDED`. A payer contract whose blended transition impact is materially erosive may still be activated, but only when the activating request carries `erosion_override_ack` set to true; material erosion means a blended impact at or below negative 500,000 cents (a loss of five thousand dollars a year or worse), and an impact of exactly negative 500,000 cents counts as material. Without the acknowledgement the activation is rejected with `ERR_FEE_EROSION_MATERIAL`.

### 2.6. Integration Posture: The Derived Gate Over Every Practice

Each practice carries an `integration_posture` that no client ever writes. It is derived from the practice's own `affiliation_status`, its five integration counters and its chart target, and it is recomputed on every write that changes any of those inputs. The derivation is a precedence ladder, and the first clause that matches decides the answer — later clauses are not evaluated at all:

1. If `affiliation_status` is anything other than `AFFILIATED`, the posture is `PRE_CLOSE`.
2. Otherwise, if `active_doctor_count` is zero, the posture is `FROZEN`.
3. Otherwise, if `quarantined_batch_count` is greater than zero, or `denied_enrollment_count` is greater than zero, the posture is `RESTRICTED`.
4. Otherwise, if `pending_credentialing_count` is greater than zero, or `charts_migrated_count` is strictly less than `charts_total_expected`, the posture is `STABILIZING`.
5. Otherwise, the posture is `INTEGRATED`.

The precedence is load-bearing. Clause two dominates clauses three and four: a practice with no active doctor is `FROZEN` even when it simultaneously holds quarantined batches and denied enrollments. Clause three dominates clause four: a practice with even one quarantined batch is `RESTRICTED` even when every expected chart has migrated and nothing is pending in credentialing. Alongside the posture, the boolean `clinical_coverage_gap` is set to true exactly when the derived posture is `FROZEN`, and to false otherwise.

Posture is the gate. Scheduling a cutover, activating a fee schedule, finalizing a consolidation, standardizing staffing and harmonizing compensation all require the practice to be `STABILIZING` or `INTEGRATED`; a posture of `PRE_CLOSE`, `RESTRICTED` or `FROZEN` rejects them with `ERR_PRACTICE_POSTURE_BLOCKED`. Reporting chart-validation results is more permissive: it additionally accepts `RESTRICTED`, so a practice already demoted by one quarantined batch can still validate its remaining batches. Submitting a credentialing enrollment is the most permissive of all: it accepts any posture except `FROZEN`. Those seven operations are the complete set guarded by the posture rule.

### 2.7. Cascades, Derived Counters and Version Propagation

Consistency in this system is immediate, and it is transitive. Two transitions — closing an affiliation, and separating an active doctor — each set off a chain in which every hop is caused by the state change the previous hop wrote, not by the originating call. A hop that changes a row mutates that row: `updated_at` is refreshed and `version` increments by one, on every row the cascade touches, not only on the row the client addressed. When a cascade increments a counter on a practice and the recomputed posture then changes, both the counter write and the posture write are part of the same mutation and the practice's `version` advances. The rule is not special to cascades: on *every* request, any row whose derived counters or derived enums move as a consequence of that request is mutated exactly once by it — the conversion vendor whenever its `active_window_count` moves, the payer contract whenever its `enrollment_open_count`, `fee_schedule_item_count` or `blended_impact_cents` moves, the agreement whenever its `line_item_count` moves, the employment whenever its `credentialing_status` rollup moves, the practice whenever any of its five counters or its posture moves, the affiliation whenever `practice_count` or a pool bucket moves — and no row's `version` ever advances by more than one step inside a single request, however many hops touched it.

Derived counters are never client-writable and are always maintained by the child workflows that own them. On a practice, `active_doctor_count` counts the employment rows of that practice whose `employment_status` is `ACTIVE`; `charts_migrated_count` sums `records_validated` over that practice's batches whose status is `VALIDATED` or `RECONCILED`; `pending_credentialing_count` counts the enrollments reachable from that practice whose status is `SUBMITTED`; `denied_enrollment_count` counts those whose status is `DENIED`; and `quarantined_batch_count` counts the practice's batches whose status is `QUARANTINED`. On an affiliation, `practice_count` counts the practices naming it. On a conversion vendor, `active_window_count` counts the batches in status `SCHEDULED` whose practice names that vendor. On an agreement, `line_item_count` counts its scope lines. On a payer contract, `fee_schedule_item_count` counts its priced procedures and `enrollment_open_count` counts its enrollments in status `NOT_STARTED` or `SUBMITTED`.

Because derived values are recomputed rather than remembered, a compensating operation must restore them exactly. Rolling back a validated migration batch and clawing back a settled earn-out tranche are both defined so that the affected roll-ups return to precisely the values they held before the operation being compensated, with zero drift.

### 2.8. Conserved-Quantity Ledgers

Two quantities in this system are conserved: earn-out cents and migrated chart records. Neither is ever created or destroyed by a workflow; both only move between buckets.

The **earn-out pool ledger** governs one affiliation. `earnout_reserved_cents` is the sum of `reserved_cents` over that affiliation's tranches whose status is `RESERVED`. `earnout_settled_cents` is the sum of `awarded_cents` over that affiliation's tranches whose status is `SETTLED`. `earnout_unallocated_cents` is `earnout_pool_cents` less `earnout_reserved_cents` less `earnout_settled_cents`. The invariant that must hold after every single write is that `earnout_pool_cents` equals the sum of `earnout_unallocated_cents`, `earnout_reserved_cents` and `earnout_settled_cents`. `earnout_unallocated_cents` must never be negative: any reservation or settlement that would drive it below zero is refused with `ERR_EARNOUT_POOL_EXCEEDED` and leaves all four figures exactly as they were. Repricing a deal, reserving a tranche, settling a tranche and clawing a tranche back are the four writes that move cents inside this ledger, and no rounding occurs anywhere in the identity.

The **chart records ledger** governs one practice and its batches. The practice-level invariant is that `charts_migrated_count` equals the sum of `records_validated` over that practice's batches whose status is `VALIDATED` or `RECONCILED`. The per-batch invariant is that each batch's `records_total` equals the sum of its `records_validated`, its `records_quarantined` and its `records_pending`. Both invariants must hold after every write that touches a batch — validation, remediation, rollback and reconciliation alike — and a rollback must return the practice's chart count to its exact pre-validation value even when several other batches validated in between.

### 2.9. Stale-Parent-Version Rejection on Parent-Scoped Creates

Two create operations carry a mandatory optimistic-concurrency field naming the parent they are being written against. These fields are not optional and are not defaulted; a request that omits them fails payload validation.

A request to `POST /dso/earnout-tranches` must carry `expected_affiliation_version` holding the client's last observed `version` of the target `Affiliation`. If that value does not equal the affiliation's current `version`, the create is rejected with `ERR_STALE_AFFILIATION_VERSION` and HTTP 412. A newly projected tranche legitimately supersedes the prior projection for the same pool, so a writer holding a stale view of `earnout_unallocated_cents` would otherwise project against a pool balance that no longer exists.

A request to `POST /dso/migration-batches` must carry `expected_practice_version` holding the client's last observed `version` of the target `Practice`. If that value does not equal the practice's current `version`, the create is rejected with `ERR_STALE_PRACTICE_VERSION` and HTTP 412. A successful create supersedes every earlier staged batch of that practice, so a writer whose view of the practice's chart counters is stale would silently discard a batch mapping produced from newer counters.

No other endpoint in this API accepts a version field, and no other endpoint performs a version comparison. Operations not named above proceed without any concurrency check.

### 2.10. Resource Addressing and Left-to-Right Path Resolution

The entity topology is flat: every entity is addressed at its own top-level collection under `/dso`, and no endpoint nests two entity identifiers in its path. Parent linkage is expressed exclusively through foreign-key fields in request bodies, and reverse navigation is provided by filtered list endpoints plus five sub-resource readers — a practice's vendor consolidations, an employment's supply preference exceptions, an employment's clinical quality reviews, an agreement's line items and a contract's fee schedule items. Those five readers and the two nested creates use `id` as the name of their path variable; every other templated path uses the entity-specific name (`affiliation_id`, `practice_id`, `doctor_id`, `conversion_vendor_id`, `doctor_employment_id`, `service_agreement_id`, `migration_batch_id`, `payer_contract_id`, `payer_enrollment_id`, `earnout_tranche_id`, `supply_preference_exception_id`, `vendor_consolidation_id`, `clinical_quality_review_id`).

Templated path segments are resolved strictly left to right, and the first segment that does not name an existing row terminates the request with the 404 code belonging to the entity that the collection segment names: `ERR_AFFILIATION_NOT_FOUND`, `ERR_PRACTICE_NOT_FOUND`, `ERR_DOCTOR_NOT_FOUND`, `ERR_CONVERSION_VENDOR_NOT_FOUND`, `ERR_DOCTOR_EMPLOYMENT_NOT_FOUND`, `ERR_SERVICE_AGREEMENT_NOT_FOUND`, `ERR_MIGRATION_BATCH_NOT_FOUND`, `ERR_PAYER_CONTRACT_NOT_FOUND`, `ERR_PAYER_ENROLLMENT_NOT_FOUND`, `ERR_EARNOUT_TRANCHE_NOT_FOUND`, `ERR_SUPPLY_EXCEPTION_NOT_FOUND`, `ERR_VENDOR_CONSOLIDATION_NOT_FOUND` or `ERR_QUALITY_REVIEW_NOT_FOUND`. Foreign keys supplied in a request body are resolved after every path segment has resolved and before the payload's shape is checked, in the order the endpoint declares them — `affiliation_id` before `conversion_vendor_id` on a practice create, `practice_id` before `doctor_id` on an employment create, `payer_contract_id` before `doctor_employment_id` on an enrollment create — so a body that omits one foreign key while naming another that does not exist reports the missing row's 404 rather than the absent field's `ERR_INVALID_REQUEST`; and they raise the same family of 404 codes: a body naming a missing affiliation raises `ERR_AFFILIATION_NOT_FOUND`, a missing practice raises `ERR_PRACTICE_NOT_FOUND`, a missing doctor raises `ERR_DOCTOR_NOT_FOUND`, a missing conversion vendor raises `ERR_CONVERSION_VENDOR_NOT_FOUND`, a missing employment raises `ERR_DOCTOR_EMPLOYMENT_NOT_FOUND`, a missing agreement raises `ERR_SERVICE_AGREEMENT_NOT_FOUND` and a missing payer contract raises `ERR_PAYER_CONTRACT_NOT_FOUND`.

### 2.11. Request Evaluation Order and Error Precedence

Every request runs through one ordered gauntlet of checks. The first check whose condition is violated determines the response, no later check is evaluated, and **no state change whatsoever is written** when any check fires. The order below is the complete precedence, from highest priority to lowest; where a family contains several checks, they too are listed in their own precedence order.

1. Identity headers present and non-empty on every endpoint — `ERR_UNAUTHENTICATED` (401).
2. Role recognized and authorized for this endpoint — `ERR_UNAUTHORIZED` (403).
3. Entity-backed identity resolves to an existing `Doctor` row, on the seven clinician operations named in §2.1 — `ERR_UNAUTHORIZED` (403).
4. Path-resource existence, resolved left to right — the entity's 404 code.
5. Body foreign-key existence — the referenced entity's 404 code.
6. Payload shape — `ERR_INVALID_REQUEST` (400). Every required body field must be present with its declared type; enum fields must carry a declared value; money and count fields must be integers inside their declared range; date-time fields must be ISO 8601 UTC; `monthly_collections_cents` must hold exactly twelve entries; `measurement_end` must be strictly after `measurement_start`; `cutover_end_at` must be strictly after `cutover_start_at`; `term_date`, when supplied, must be strictly after `effective_date`; and pagination must satisfy §2.3. Body fields the endpoint does not declare are ignored rather than rejected.
7. `expected_affiliation_version` matches the affiliation's current `version`, on tranche creation — `ERR_STALE_AFFILIATION_VERSION` (412).
8. `expected_practice_version` matches the practice's current `version`, on batch creation — `ERR_STALE_PRACTICE_VERSION` (412).
9. Affiliation status permits the operation — `ERR_INVALID_AFFILIATION_STATE` (409). Guards advancing to diligence, repricing, signing, closing, making an agreement effective and reserving a tranche.
10. Earn-out tranche status permits the operation — `ERR_INVALID_TRANCHE_STATE` (409). Deliberately far above the pool-capacity check at position 49, so that a tranche that is both wrongly staged and unaffordable reports the state error.
11. The addressed employment dimension is in its required state — `ERR_INVALID_EMPLOYMENT_STATE` (409). Guards accepting an offer, harmonizing compensation, separating, transferring custody, enforcing the covenant, requesting and deciding a preference exception, opening a quality review, and creating and submitting an enrollment.
12. Migration batch status permits the operation — `ERR_INVALID_BATCH_STATE` (409).
13. Payer enrollment status permits the operation — `ERR_INVALID_ENROLLMENT_STATE` (409).
14. Service agreement status permits the operation — `ERR_INVALID_AGREEMENT_STATE` (409).
15. Payer contract transition state permits the operation — `ERR_INVALID_CONTRACT_STATE` (409).
16. The single-decision workflows are in their opening state — `ERR_INVALID_WORKFLOW_STATE` (409). Exactly three operations sit here: deciding a supply preference exception (which must be `REQUESTED`), finalizing a vendor consolidation (which must be `PLANNED`) and closing a clinical quality review (which must be `OPEN`).
17. The practice reached by the operation has `affiliation_status` equal to `AFFILIATED` — `ERR_PRACTICE_NOT_AFFILIATED` (409). Guards scheduling a cutover, activating a fee schedule, submitting an enrollment, finalizing a consolidation, standardizing staffing and harmonizing compensation.
18. The practice's derived posture permits the operation, per §2.6 — `ERR_PRACTICE_POSTURE_BLOCKED` (409).
19. A doctor's licensure matches the employing practice's jurisdiction — `ERR_LICENSE_STATE_MISMATCH` (422).
20. The corporate-practice boundary, per §2.12 — `ERR_CORPORATE_PRACTICE_VIOLATION` (422).
21. No self-review of a clinician's own charts — `ERR_SELF_REVIEW_PROHIBITED` (422).
22. Segregation of duties on earn-out settlement — `ERR_SEGREGATION_OF_DUTIES` (403).
23. The restrictive covenant has not yet expired — `ERR_NON_COMPETE_EXPIRED` (422).
24. The affiliation has at least one target practice — `ERR_NO_TARGET_PRACTICE` (422).
25. Every practice of the affiliation has post-close employment terms on the table — `ERR_NO_POST_CLOSE_EMPLOYMENT` (422).
26. The required management services agreement is effective — `ERR_SERVICE_AGREEMENT_NOT_EFFECTIVE` (422).
27. The agreement has at least one scope line — `ERR_SERVICE_SCOPE_EMPTY` (422).
28. The payer contract has at least one priced procedure — `ERR_FEE_SCHEDULE_EMPTY` (422).
29. The payer contract has at least one enrollment and all of them are approved — `ERR_ENROLLMENTS_NOT_APPROVED` (422). Deliberately ordered above the lead-time check at position 34, so that a contract that is both un-credentialed and short on lead time reports the referential failure.
30. Enrollment participation intervals do not overlap — `ERR_ENROLLMENT_PERIOD_OVERLAP` (409).
31. Cutover windows of the same practice respect the mandatory buffer — `ERR_CUTOVER_WINDOW_CONFLICT` (409). Ordered above the vendor-capacity check at position 37.
32. Earn-out measurement periods of the same affiliation do not overlap — `ERR_MEASUREMENT_PERIOD_OVERLAP` (409).
33. The batch's cutover window has opened — `ERR_CUTOVER_WINDOW_NOT_STARTED` (409).
34. Every enrollment of the contract clears the credentialing lead time — `ERR_CREDENTIALING_LEAD_TIME_SHORT` (422).
35. A provisional reservation has at least one elapsed measurement day — `ERR_MEASUREMENT_PERIOD_NOT_STARTED` (422).
36. The logical clock does not move backwards — `ERR_CLOCK_NOT_MONOTONIC` (422).
37. The conversion vendor has crew capacity for the requested window — `ERR_VENDOR_WINDOW_CAPACITY` (409).
38. A batch cannot quarantine more records than it staged — `ERR_QUARANTINE_COUNT_EXCEEDS_TOTAL` (422).
39. A quality review's sample clears the statistical floor — `ERR_SAMPLE_SIZE_TOO_SMALL` (422).
40. A National Provider Identifier is unique across all doctors — `ERR_DUPLICATE_NPI` (409).
41. A procedure code is unique inside its payer contract — `ERR_DUPLICATE_PROCEDURE_CODE` (409).
42. A service code is unique inside its agreement — `ERR_DUPLICATE_SERVICE_CODE` (409).
43. The repricing loop has rounds left — `ERR_REPRICING_LIMIT_REACHED` (422).
44. The earn-out pool is not yet locked by a projected tranche — `ERR_EARNOUT_POOL_LOCKED` (409).
45. The requested close outcome matches the review's computed score — `ERR_QUALITY_OUTCOME_MISMATCH` (422).
46. The standardized hygiene ratio is inside its permitted band — `ERR_STAFFING_RATIO_OUT_OF_RANGE` (422).
47. The management fee respects its cap at the moment of effectiveness — `ERR_MGMT_FEE_CAP_EXCEEDED` (422).
48. Material fee erosion carries an explicit acknowledgement — `ERR_FEE_EROSION_MATERIAL` (422).
49. The computed earn-out payout fits the available pool — `ERR_EARNOUT_POOL_EXCEEDED` (422). Deliberately the lowest-priority fiscal check, so a stale or wrongly-staged tranche reports its own state error first.
50. Compensation harmonization respects its uplift cap — `ERR_COMP_HARMONIZATION_CAP_EXCEEDED` (422). The compensation calculation runs first and its result is then bounded.

### 2.12. The Corporate-Practice-of-Dentistry Boundary

The support organization sells non-clinical support and nothing else. Two rules draw that line inside the API, and both raise `ERR_CORPORATE_PRACTICE_VIOLATION`.

First, the management services agreement may never buy clinical judgement. A scope line whose `service_domain` falls in the clinical set — `TREATMENT_PLANNING`, `CLINICAL_SUPERVISION` or `DIAGNOSIS` — is refused outright, so the computed `is_clinical` flag on a persisted scope line is always false; the flag exists precisely because a clinical domain never survives to be stored. The non-clinical domains that may be purchased are `BILLING`, `HR`, `PROCUREMENT`, `IT`, `MARKETING`, `FACILITIES` and `CREDENTIALING`.

Second, clinical oversight may only be exercised by a locally licensed clinician. Closing a clinical quality review requires that the `license_state` on the closing `ClinicalDirector`'s own doctor record equal the `state_code` of the practice at which the reviewed employment sits. A director licensed in a different jurisdiction cannot sign off on charts written under a licence they do not hold, however senior they are inside the support organization. Clinical determinations — the outcome of a quality review, and the approval or denial of a clinician preference exception — are reserved to `ClinicalDirector` and are unavailable to every non-clinical role.

## 3. Business Logic & Workflows

### 3.1. Deal Origination and the Path to Signature

Transaction counsel opens an **affiliation** — the transaction file for one selling dental group — by supplying the group's `seller_group_name`, the cash-at-close `purchase_price_cents` (at least 1), the maximum aggregate `earnout_pool_cents` (zero or more), the trailing-twelve-month `baseline_ebitda_cents` (at least 1) and the trailing-twelve-month `baseline_net_collections_cents` (at least 1), together with `post_close_doctor_term_months`, the deal-level default employment term, which must be zero or more and defaults to 36 months when omitted. A newly opened file begins in `DRAFT` with `repricing_round` and `practice_count` at zero, `earnout_reserved_cents` and `earnout_settled_cents` at zero, `earnout_unallocated_cents` equal to the whole `earnout_pool_cents`, `earnout_measurement_state` at `NOT_OPEN`, and `diligence_opened_at`, `signed_date` and `close_date` all still empty. The two baseline figures are recorded at origination and never change: the EBITDA baseline is the yardstick every earn-out measurement is compared against, while the net-collections baseline is retained as the deal's collections reference.

Before charts can be converted, the integration lead registers the **conversion vendors** who will do the converting. A vendor is created with a `name` and a `max_concurrent_windows` crew capacity of at least one, and its `active_window_count` starts at zero. That capacity is a hard aggregate ceiling across every practice the vendor serves, not a per-practice allowance.

Target **practices** are then attached to the file. Either transaction counsel or the integration lead may add one, naming the owning `affiliation_id`, the `conversion_vendor_id` that will perform the system conversion, the practice's trade `name`, its `state_code` (exactly two uppercase letters identifying the licensing jurisdiction) and `charts_total_expected`, the number of patient charts expected to migrate from the legacy system, which must be at least one. A new practice begins with `affiliation_status` of `PENDING`, an `integration_posture` of `PRE_CLOSE`, a `staffing_model_state` of `LEGACY`, an empty `fte_hygiene_ratio_bps`, every integration counter at zero — `active_doctor_count`, `charts_migrated_count`, `pending_credentialing_count`, `denied_enrollment_count` and `quarantined_batch_count` — and `clinical_coverage_gap` false. Attaching a practice increments the affiliation's `practice_count` and its `version`.

Doctors are registered independently of any practice. A doctor record carries a `full_name`, a ten-digit `npi`, a `license_number`, a two-uppercase-letter `license_state`, an optional `specialty` drawn from `GENERAL`, `ENDODONTICS`, `ORTHODONTICS`, `ORAL_SURGERY` and `PERIODONTICS` and defaulting to `GENERAL`, and an optional `is_seller_owner` flag defaulting to false that marks a selling owner of the target group. No two doctor records may share an identifier: a second registration of an `npi` already on file is refused with `ERR_DUPLICATE_NPI`.

Post-close employment terms are offered before the deal is signed, not after. The integration lead offers terms at a practice by naming the `practice_id` and the `doctor_id` and supplying the guaranteed `base_salary_monthly_cents` (zero or more), the doctor's `collections_pct_bps` share of their own net collections (between 0 and 5,000 basis points inclusive, so at most half of collections), the `legacy_annual_comp_cents` pre-affiliation package that the harmonization delta will later be measured against, the `post_close_term_months` term — which takes the affiliation's `post_close_doctor_term_months` default when the offer omits it — and the restrictive covenant's `non_compete_months` (between 0 and 24 inclusive) and `non_compete_radius_miles` (between 0 and 15 inclusive). An optional `comp_model` selects the contractual compensation variant and defaults to `MONTHLY_MIN_GUARANTEE`; the alternative is `ANNUAL_TRUE_UP`. Licensure is checked against geography here: the doctor's `license_state` must equal the practice's `state_code`, and a mismatch is refused with `ERR_LICENSE_STATE_MISMATCH`. A fresh offer begins with `employment_status` at `OFFERED` and `offer_accepted` false, with `credentialing_status` at `PENDING`, `records_custody_state` at `HELD_BY_PRACTICE` and `non_compete_enforcement_state` at `NOT_APPLICABLE`, with `is_harmonized` false and `harmonized_annual_comp_cents`, `harmonization_delta_cents`, `comp_effective_date`, `non_compete_end_date`, `separation_date` and `separation_reason` all still empty.

Counsel then walks the file forward. Opening diligence moves the affiliation `DRAFT → DILIGENCE` and stamps `diligence_opened_at` from the logical clock; it requires the file to be in `DRAFT` and requires `practice_count` to be at least one, since diligence cannot open on a deal with nothing to buy — an empty file is refused with `ERR_NO_TARGET_PRACTICE`. Diligence sometimes goes badly, and the only path back is a **reprice**, which returns the file `DILIGENCE → DRAFT`. Repricing overwrites `purchase_price_cents` and `earnout_pool_cents` with new figures, accepts an optional `reprice_note`, recomputes `earnout_unallocated_cents` against the new pool, and increments `repricing_round`. The loop terminates: at most two repricing rounds may be consumed, so a third attempt — one made while `repricing_round` already stands at 2 — is refused with `ERR_REPRICING_LIMIT_REACHED`. Repricing also becomes impossible once the pool has been committed against: if even one earn-out tranche exists for the affiliation, the pool size is frozen and the attempt is refused with `ERR_EARNOUT_POOL_LOCKED`. Both of these are checked in the order given by §2.11, after the file's `DILIGENCE` status has been confirmed.

Signing carries the file `DILIGENCE → SIGNED`, stamps `signed_date` from the logical clock and accepts an optional `signature_note`. It requires that every practice of the affiliation have at least one employment row in `OFFERED` status, because the support organization will not sign for a practice with no post-close clinical coverage on the table; a practice without one blocks signature with `ERR_NO_POST_CLOSE_EMPLOYMENT`.

### 3.2. Non-Clinical Support Scope: The Management Services Agreement

Each practice receives support services under a **management services agreement** drafted by transaction counsel. Creating one names the `practice_id`, selects a `fee_model` of either `PCT_OF_COLLECTIONS` or `FIXED_MONTHLY`, and sets a `mgmt_fee_bps` management fee expressed in basis points of net collections. The agreement opens in `DRAFT` with `review_round`, `scope_findings_count` and `line_item_count` all at zero and no `effective_date`.

Scope is assembled line by line while the agreement is in `DRAFT`. Each **scope line** names a `service_code` from the support-service catalogue, a `service_domain`, and the `monthly_fee_cents` attributed to that line (zero or more). A service code may appear only once per agreement; a repeat is refused with `ERR_DUPLICATE_SERVICE_CODE`. The corporate-practice screen of §2.12 applies here, so a clinical domain never persists and the stored `is_clinical` value is always false. Each accepted line increments the agreement's `line_item_count` and its `version`; the line itself carries only an `id` and a `created_at`, since scope lines are written once and never revised.

Submitting the drafted scope for corporate-practice legal review moves the agreement `DRAFT → LEGAL_REVIEW` and increments `review_round`; a submission is refused with `ERR_SERVICE_SCOPE_EMPTY` when `line_item_count` is still zero. Review may reject the scope, which returns the agreement `LEGAL_REVIEW → DRAFT` and adds the request's `finding_count` — a mandatory integer of zero or more — to the cumulative `scope_findings_count`, optionally recording a `finding_note`. This revision loop has no round limit: an agreement may be resubmitted and rejected any number of times, with `review_round` counting submissions and `scope_findings_count` accumulating findings across all of them. Scope may only be edited in `DRAFT`, so line-item additions and submission both require `DRAFT`, while rejection and making the agreement effective both require `LEGAL_REVIEW`; a request against the wrong status is refused with `ERR_INVALID_AGREEMENT_STATE`, and because `EFFECTIVE` is terminal, no scope edit is possible once the agreement is live.

Making the agreement effective carries it `LEGAL_REVIEW → EFFECTIVE` and stamps `effective_date` from the logical clock. Three conditions are checked in the order of §2.11, which places the affiliation gate at position 9 above the agreement gate at position 14: first, the affiliation owning the agreement's practice must be in `SIGNED` or `CLOSED`, and any other affiliation status is refused with `ERR_INVALID_AFFILIATION_STATE`; then the agreement must be in `LEGAL_REVIEW`; and only then must the fee cap of §2.5 hold. An effective agreement is what unblocks two later gates — the affiliation's own close, and cutover scheduling at that practice.

### 3.3. Closing the Transaction and the Five-Hop Integration Cascade

Closing is the integration lead's act, it carries the affiliation `SIGNED → CLOSED`, it accepts an optional `close_note`, and it is by far the widest-reaching write in the system. It requires the file to be in `SIGNED` status, and it requires that every practice of the affiliation already hold at least one management services agreement in `EFFECTIVE` status — no support services may be rendered and no conversion begun before the agreement is live — so a practice without one blocks the close with `ERR_SERVICE_AGREEMENT_NOT_EFFECTIVE`.

The cascade then runs in five hops, and every hop after the first is caused by the state change the previous hop wrote rather than by the close call itself.

**Hop one** touches the affiliation: `close_date` is stamped from the logical clock, `earnout_measurement_state` moves `NOT_OPEN → OPEN`, and the affiliation's `version` increments by one.

**Hop two** is caused by hop one. Every practice of the affiliation has its `affiliation_status` moved `PENDING → AFFILIATED`, its `integration_posture` recomputed by the ladder of §2.6 — which takes it out of `PRE_CLOSE` and, once the next hop supplies at least one active doctor, lands it at `STABILIZING`, the transition `PRE_CLOSE` → `STABILIZING` — and its `version` incremented by one.

**Hop three** is caused by hop two's posture change leaving `PRE_CLOSE`. At each such practice, every employment row in `OFFERED` status splits by whether the doctor had already accepted. Rows with `offer_accepted` true move `OFFERED → ACTIVE`, have `comp_effective_date` set to the affiliation's `close_date`, increase that practice's `active_doctor_count` by one, and have their own `version` incremented by one. Rows with `offer_accepted` false at the moment the cascade runs move `OFFERED → LAPSED`, leave `active_doctor_count` untouched, and likewise have their `version` incremented by one. Both branches are written; neither is skipped.

**Hop four** is caused by hop three's activations. For each employment row that has just become `ACTIVE`, one credentialing enrollment is created against every payer contract of that employment's practice whose `transition_state` is still `LEGACY`, processed in the payer contracts' `created_at` ascending order. Each created enrollment opens in `NOT_STARTED`, with its `effective_date` set to the affiliation's `close_date` plus the ninety-day credentialing lead time and its `term_date` left empty, meaning open-ended.

**Hop five** is caused by hop four's enrollment creation. Every payer contract whose `enrollment_open_count` has just moved from zero to a positive value transitions `LEGACY → PENDING_CREDENTIALING` and has its `version` incremented by one.

### 3.4. The Employment Row and Its Three Independent Dimensions

An employment row carries three state dimensions that advance independently of one another on the same row. `employment_status` is the contractual dimension and runs `OFFERED`, `ACTIVE`, `LAPSED`, `SEPARATED`, with `LAPSED` and `SEPARATED` terminal. `credentialing_status` is a derived dimension taking the values `PENDING`, `SUBMITTED`, `APPROVED` and `DENIED`. `records_custody_state` is the patient-records dimension and runs `HELD_BY_PRACTICE`, `TRANSFER_PENDING`, `TRANSFERRED`. A fourth, narrower dimension tracks the restrictive covenant through `non_compete_enforcement_state`, which runs `NOT_APPLICABLE`, `PENDING`, `ENFORCED`. An operation that advances one dimension leaves the others exactly where they were, and every request addressing a dimension that is not in the state the operation needs is refused with `ERR_INVALID_EMPLOYMENT_STATE`.

**Accepting an offer** is a dentist's own act, and it forks on where the deal stands. In both branches the row must be in `OFFERED` with `offer_accepted` still false; an already-accepted offer is refused. When the affiliation is anything other than `CLOSED` — `SIGNED` in the ordinary case, but equally `DRAFT` or `DILIGENCE` if terms are accepted that early — acceptance only records consent: `offer_accepted` becomes true, `employment_status` deliberately stays at `OFFERED` — the self-transition `OFFERED` → `OFFERED` — and activation is deferred to the close cascade of §3.3, which will find `offer_accepted` true at hop three. When the affiliation is already `CLOSED` — the post-close replacement-hire branch of the same operation — acceptance activates the employment immediately: `offer_accepted` becomes true, `employment_status` moves `OFFERED → ACTIVE`, `comp_effective_date` is stamped from the logical clock rather than from the close date, the practice's `active_doctor_count` increases by one, the practice's posture is recomputed, and both the employment row's `version` and the practice's `version` increment by one. That posture recomputation is what releases a frozen practice: bringing `active_doctor_count` back to one or more moves a practice `FROZEN → STABILIZING`, sets `clinical_coverage_gap` back to false, returns every batch of that practice from `HELD` to `SCHEDULED` and every enrollment from `SUSPENDED` back to `SUBMITTED`, and — when no other practice of the affiliation remains frozen — moves the affiliation's `earnout_measurement_state` from `SUSPENDED` back to `OPEN`.

The **credentialing dimension** is never written by a client. It is recomputed from the enrollment rows referencing the employment whenever any of their statuses changes, including during the close cascade that creates them, and it never reads either of the other two dimensions. The precedence ladder is: if the employment has no enrollments at all, the rollup is `PENDING`; otherwise, if any one enrollment is `DENIED`, the rollup is `DENIED`; otherwise, if every enrollment is `APPROVED`, the rollup is `APPROVED`; otherwise, if any enrollment is `SUBMITTED`, the rollup is `SUBMITTED`; otherwise the rollup is `PENDING`. A single denial therefore dominates any number of approvals, because the denial clause is evaluated before the all-approved clause. A `SUSPENDED` enrollment counts as neither approved nor submitted, so freezing a practice pulls the rollup back to `PENDING`. Each recomputation increments the employment row's `version` by one.

**Harmonizing compensation** is the finance controller's act and requires an `ACTIVE` employment at an `AFFILIATED` practice whose posture is `STABILIZING` or `INTEGRATED`. The request supplies `monthly_collections_cents`, an array of exactly twelve integer cent figures, each zero or more, with month one first, covering the first twelve months of the employment term. Both contractual variants consume that identical series together with the identical `base_salary_monthly_cents` and `collections_pct_bps`, and they generally disagree because they aggregate at different granularities.

Under `MONTHLY_MIN_GUARANTEE`, the guarantee is a per-month floor. For each of the twelve months in turn, the doctor's percentage share for that month is the month's collections multiplied by `collections_pct_bps` and divided by ten thousand, rounded half up to whole cents; that month's pay is the greater of `base_salary_monthly_cents` and that rounded share; and `harmonized_annual_comp_cents` is the sum of the twelve monthly pay figures. Rounding therefore happens twelve times, once per month.

Under `ANNUAL_TRUE_UP`, the guarantee is an annual floor. The twelve monthly collections are summed first, exactly and without rounding; the doctor's percentage share is that annual total multiplied by `collections_pct_bps` and divided by ten thousand, rounded half up to whole cents exactly once; and `harmonized_annual_comp_cents` is the greater of that single rounded share and `base_salary_monthly_cents` multiplied by twelve.

The difference is not cosmetic. A month whose collections fall below the guarantee is topped up to the base salary under `MONTHLY_MIN_GUARANTEE` and that top-up is never clawed back by a strong month, whereas `ANNUAL_TRUE_UP` lets strong months absorb weak ones. The monthly variant is therefore always greater than or equal to the annual variant on identical inputs, and strictly greater whenever any month falls below the guarantee while the annual percentage still clears twelve times the base. Whichever variant ran, the result is then compared against `legacy_annual_comp_cents`: `harmonization_delta_cents` is `harmonized_annual_comp_cents` less `legacy_annual_comp_cents`, and `is_harmonized` becomes true. The uplift cap of §2.11 position 50 bounds the result after the calculation has run — the harmonized figure may not exceed the legacy package multiplied by 12,500 and divided by ten thousand, which is to say one hundred and twenty-five percent of the legacy package. That comparison is exact and carries no rounding step of its own: the harmonized figure scaled by ten thousand is compared against the legacy package scaled by 12,500, so a legacy package of zero admits only a harmonized figure of zero. A result above the ceiling is refused with `ERR_COMP_HARMONIZATION_CAP_EXCEEDED` with nothing written.

**Separation** records a doctor's departure. Either the integration lead or the departing dentist may perform it, it requires `employment_status` to be `ACTIVE`, and it supplies a `separation_reason` of `VOLUNTARY`, `TERMINATED_FOR_CAUSE` or `NON_RENEWAL`. It is the second five-hop cascade in the system, and like the close cascade each hop is caused by what the previous hop wrote.

Hop one touches the employment row: `employment_status` moves `ACTIVE → SEPARATED`, `separation_date` is stamped from the logical clock, `separation_reason` is recorded from the request, `non_compete_end_date` is set to `separation_date` advanced by `non_compete_months` calendar months with end-of-month clamping, so a 31 January separation advanced by one month lands on the last day of February and a covenant of zero months lands on `separation_date` itself, `records_custody_state` moves `HELD_BY_PRACTICE → TRANSFER_PENDING`, `non_compete_enforcement_state` moves `NOT_APPLICABLE → PENDING`, and the practice's `active_doctor_count` decreases by one.

Hop two is caused by that counter change. When `active_doctor_count` reaches zero, the posture ladder of §2.6 returns `FROZEN`, so the practice moves `STABILIZING` → `FROZEN` — or `RESTRICTED` → `FROZEN`, or `INTEGRATED` → `FROZEN`, depending on where it stood — `clinical_coverage_gap` is set to true, and the practice's `version` increments by one.

Hop three is caused by hop two's posture change. Every migration batch of that practice in `SCHEDULED` status moves `SCHEDULED → HELD`, keeping its reserved `cutover_start_at` and `cutover_end_at`, and every enrollment of that practice in `SUBMITTED` status moves `SUBMITTED → SUSPENDED`.

Hop four is caused by hop three. Each held batch reduces its practice's conversion vendor's `active_window_count` by one, and each suspended enrollment reduces the practice's `pending_credentialing_count` by one and its payer contract's `enrollment_open_count` by one.

Hop five is caused by hop four's counter reductions. Every payer contract whose `enrollment_open_count` has reached zero while its `transition_state` is `PENDING_CREDENTIALING` reverts `PENDING_CREDENTIALING → LEGACY`, provided no enrollment of that contract is `APPROVED`; each such reversion increments the contract's `version` by one. Separately, the parent affiliation's `earnout_measurement_state` moves to `SUSPENDED`, which stops earn-out reservations for the whole deal while any of its practices is frozen.

Two narrower operations act on a separated employment without disturbing its contractual dimension. The clinical director, as custodian of patient records after a departure, **transfers records custody**, optionally recording a `custodian_note`; this requires `employment_status` to be `SEPARATED` and `records_custody_state` to be `TRANSFER_PENDING`, and it advances `records_custody_state` to `TRANSFERRED` while leaving `employment_status` at `SEPARATED` and `credentialing_status` untouched. Transaction counsel **enforces the restrictive covenant**, optionally recording an `enforcement_note`; this requires `employment_status` to be `SEPARATED`, requires `non_compete_enforcement_state` to be `PENDING`, and requires the logical clock to be strictly earlier than `non_compete_end_date`, since a covenant cannot be asserted once its own term has run — a clock at or after that instant is refused with `ERR_NON_COMPETE_EXPIRED`. On success, `non_compete_enforcement_state` moves `PENDING → ENFORCED` and the row's `version` increments by one.

### 3.5. Chart Migration: Staging, Cutover Windows and Validation Outcomes

Chart migration proceeds in batches, each staged by the integration lead against one practice. Staging names the `practice_id`, gives the batch a human `batch_label`, declares `records_total` (at least one chart record), and carries the `expected_practice_version` guard of §2.9. A newly staged batch opens in `STAGED` with `records_validated` and `records_quarantined` at zero, `records_pending` equal to `records_total`, `remediation_round` at zero, no `cutover_start_at` or `cutover_end_at`, and no `validation_error_rate_bps`. Staging is exclusive per practice: every earlier batch of the same practice still in `STAGED` status is moved `STAGED → SUPERSEDED`, processed in `created_at` ascending order, with each superseded batch's `version` incremented by one, and the practice's own `version` incremented by one. `SUPERSEDED` is terminal, as is `RECONCILED`.

**Reserving a cutover window** carries the batch `STAGED` → `SCHEDULED`, or `QUARANTINED` → `SCHEDULED` when the batch is being rescheduled after a failed round, and stores the requested `cutover_start_at` and `cutover_end_at`, which describe a closed interval inclusive of both endpoints. It is the most heavily guarded operation in the system, and its conditions are evaluated in the order of §2.11. The batch must be in `STAGED` or in `QUARANTINED`; the practice must be `AFFILIATED`; the practice's posture must be `STABILIZING` or `INTEGRATED`; the practice must hold at least one `EFFECTIVE` management services agreement, or the request is refused with `ERR_SERVICE_AGREEMENT_NOT_EFFECTIVE`; the requested window must respect the practice-level buffer; and only then is the vendor's aggregate capacity examined. On success the conversion vendor's `active_window_count` increases by one and the vendor's own `version` increments by one, and the batch's `version` increments by one.

The **buffer rule** is a mandatory 48-hour separation between the requested closed window and the closed window of every other batch of the *same* practice whose status is `SCHEDULED` or `HELD`. The requested window is acceptable when its `cutover_start_at` falls at or after the existing window's `cutover_end_at` advanced by 48 hours, or when its `cutover_end_at` advanced by 48 hours falls at or before the existing window's `cutover_start_at`. A gap of exactly 48 hours is therefore allowed and a gap of 47 hours 59 minutes is not; a violation is refused with `ERR_CUTOVER_WINDOW_CONFLICT`. The **vendor capacity rule** looks wider, across every practice the vendor serves: the number of batches in status `SCHEDULED` or `HELD` on the same conversion vendor whose closed window intersects the requested closed window must be strictly less than that vendor's `max_concurrent_windows`, and a request that would meet or exceed the crew count is refused with `ERR_VENDOR_WINDOW_CAPACITY`. Each individual window can be perfectly legal at its own practice while the collective exceeds what the vendor's crews can staff.

**Reporting validation results** happens inside the reserved window and branches on the measured error rate. Its conditions run in the order of §2.11: the batch must be `SCHEDULED`; the practice's posture must be `STABILIZING`, `INTEGRATED` or `RESTRICTED`; and only then must the logical clock be at or after the batch's `cutover_start_at`, an earlier clock being refused with `ERR_CUTOVER_WINDOW_NOT_STARTED`. No separate `affiliation_status` gate applies here, because a practice that is not yet `AFFILIATED` is already stopped by its `PRE_CLOSE` posture. The request supplies `quarantined_count`, which may not exceed the batch's `records_total` — a larger figure is refused with `ERR_QUARANTINE_COUNT_EXCEEDS_TOTAL`. The rate is then `validation_error_rate_bps`, computed as `quarantined_count` multiplied by ten thousand and divided by `records_total`, rounded half up to whole basis points. Tolerance is two percent, that is 200 basis points: a rate exactly equal to 200 validates, and 201 quarantines the entire batch.

The two branches are deliberately asymmetric. On the **validating** branch, the batch moves `SCHEDULED → VALIDATED`, `records_quarantined` is set to the reported `quarantined_count`, `records_validated` is set to `records_total` less that count, `records_pending` becomes zero, the practice's `charts_migrated_count` increases by `records_validated`, the vendor's `active_window_count` decreases by one, the practice's posture is recomputed — which can carry it `STABILIZING → INTEGRATED` once `charts_migrated_count` reaches `charts_total_expected` and no other blocker remains — and both the batch's `version` and the practice's `version` increment by one. On the **quarantining** branch, the whole batch is held back rather than only the failing records: the batch moves `SCHEDULED → QUARANTINED`, `records_quarantined` is set to the full `records_total`, `records_validated` is set to zero, `records_pending` becomes zero, the practice's `charts_migrated_count` is left completely unchanged so no chart credit at all flows, the vendor's `active_window_count` still decreases by one, the practice's `quarantined_batch_count` increases by one and the recomputed posture carries the practice `STABILIZING → RESTRICTED`, and both versions increment by one. The quarantine branch's counter increment and posture demotion have no counterpart on the validating branch.

**Remediation** is the cycle edge out of quarantine, and it reuses the batch row rather than creating a new one. It requires `QUARANTINED` status, increments `remediation_round` by one, resets both `records_quarantined` and `records_validated` to zero and clears `validation_error_rate_bps`, decrements the practice's `quarantined_batch_count` by one and recomputes the posture — which carries the practice `RESTRICTED → STABILIZING` when that batch was the last blocker and at least one doctor remains active and the practice has not yet migrated all its expected charts — keeps the previously reserved cutover window in place, increases the vendor's `active_window_count` by one again, and increments both the batch's `version` and the practice's `version` by one. The batch itself moves `QUARANTINED` → `SCHEDULED`. An optional `remediation_note` may accompany the request.

**Rolling back** a validated batch is a compensating operation and must leave zero drift. It requires `VALIDATED` status and a `rollback_reason`. The practice's `charts_migrated_count` is decreased by exactly that batch's `records_validated`, then `records_quarantined` is set to `records_total` and `records_validated` to zero, the batch moves `VALIDATED → QUARANTINED`, the practice's `quarantined_batch_count` increases by one, the posture is recomputed, and both versions increment by one. Both invariants of the chart records ledger in §2.8 must hold again afterwards, and the practice's chart count must equal its exact pre-validation value even when other batches validated in between.

**Reconciling** freezes a validated batch permanently. It requires `VALIDATED` status and additionally requires `records_pending` to be zero; either failure is reported as `ERR_INVALID_BATCH_STATE`. The batch moves `VALIDATED → RECONCILED`, its `version` increments by one, and the practice's `charts_migrated_count` keeps counting that batch's `records_validated`, since reconciled batches remain inside the practice-level roll-up.

Two statuses accept no client-driven transition at all. A `HELD` batch — held by a posture freeze rather than by any operator — moves `HELD` → `SCHEDULED` only when the system observes that the practice's posture has left `FROZEN`, at which point the vendor's `active_window_count` increases by one and the batch's `version` increments. A `SUPERSEDED` batch is finished forever.

### 3.6. Payer Contract Transition, Credentialing and the DSO Fee Schedule

The finance controller registers a **payer contract** by naming the holding `practice_id` and the `payer_name` of the dental plan. It opens in `transition_state` `LEGACY`, with `fee_schedule_item_count` and `enrollment_open_count` at zero, `erosion_override_ack` false, no `blended_impact_cents` and no `dso_schedule_effective_date`. Contracts move `LEGACY → PENDING_CREDENTIALING` automatically whenever `enrollment_open_count` rises from zero to a positive value — whether by hop five of the close cascade or by an enrollment opened later — and each such transition increments the contract's `version` by one. The reverse edge exists too: a contract in `PENDING_CREDENTIALING` whose `enrollment_open_count` returns to zero because a posture freeze suspended all its open enrollments reverts to `LEGACY`, but only when no enrollment of that contract is `APPROVED`.

**Pricing** the transition is done one procedure at a time while the contract is `LEGACY` or `PENDING_CREDENTIALING`; a contract already in `DSO_SCHEDULE_ACTIVE` accepts no further priced lines and the attempt is refused with `ERR_INVALID_CONTRACT_STATE`. Each priced line names a CDT `procedure_code`, unique within its contract — a repeat is refused with `ERR_DUPLICATE_PROCEDURE_CODE` — together with the `legacy_allowed_cents` allowed amount under the seller's schedule, the `dso_allowed_cents` allowed amount under the DSO master schedule (both zero or more) and the `annual_volume` of that code at the practice (zero or more). Each line's own `line_impact_cents` is stored on the line, and the contract's `blended_impact_cents` is recomputed and the contract's `version` incremented, alongside `fee_schedule_item_count`. A priced line carries only an `id` and a `created_at`.

The blended impact is computed with the rounding boundary at the **line**, not at the contract. Processing the contract's priced lines in `created_at` ascending order, each line's raw impact is the difference between its `dso_allowed_cents` and its `legacy_allowed_cents`, multiplied by its `annual_volume`, multiplied by the utilization blend factor of 6,500 basis points — sixty-five percent — and divided by ten thousand. That raw figure is rounded half up to whole cents and stored as that line's `line_impact_cents`. The contract's `blended_impact_cents` is then the plain sum of the stored line figures, with no further rounding at the contract level. The order of operations is pinned: round each line, then sum. Summing raw values and rounding once at the end produces a different number whenever two or more lines carry a fractional half of the same sign, and the contract figure is required to reconcile exactly with the persisted line figures. A negative `blended_impact_cents` means fee erosion, and the materiality rule of §2.5 governs whether an acknowledgement is required.

**Credentialing enrollments** attach one doctor to one payer contract. The integration lead opens one by naming the `payer_contract_id` and the `doctor_employment_id`, the requested participation start `effective_date`, and optionally a `term_date` marking the exclusive end of participation; an absent `term_date` means open-ended and is compared as `9999-12-31T00:00:00Z`. The employment must be `ACTIVE`. Participation intervals are half-open, running from `effective_date` inclusive to `term_date` exclusive, and no two enrollments for the same payer-contract-and-employment pair may overlap when the existing one is `SUBMITTED` or `APPROVED`; adjacency is fine, so a new interval starting exactly at an existing interval's `term_date` is accepted, while a genuine overlap is refused with `ERR_ENROLLMENT_PERIOD_OVERLAP`. Rows in `NOT_STARTED`, `DENIED` or `SUSPENDED` status are excluded from the occupancy set entirely. A new enrollment opens in `NOT_STARTED` with `submission_round` at zero, no `lead_days`, no `submitted_at`, no `decided_at` and no `denial_reason`; it increments its contract's `enrollment_open_count` and `version`, and moves a `LEGACY` contract to `PENDING_CREDENTIALING`.

**Submitting** an enrollment runs four gates in the §2.11 order, which puts the employment dimension at position 11 above the enrollment status at position 13: it requires the referenced employment to be `ACTIVE`, then requires the enrollment itself to be in `NOT_STARTED` or `DENIED`, then requires the practice behind the contract to be `AFFILIATED`, and finally requires that practice's posture to be anything other than `FROZEN`. A first submission carries the enrollment `NOT_STARTED` → `SUBMITTED`. Submission stamps `submitted_at` from the logical clock, increments `submission_round` by one, computes `lead_days`, increments the practice's `pending_credentialing_count` by one, recomputes the employment's credentialing dimension and the practice's posture, and increments both the enrollment's `version` and the practice's `version` by one. A resubmission after denial is the same operation traversing the cycle edge `DENIED → SUBMITTED`: it additionally clears `denial_reason`, decrements the practice's `denied_enrollment_count` by one alongside incrementing `pending_credentialing_count`, and then recomputes the posture — which carries the practice `RESTRICTED → STABILIZING` when that denial was the last blocker — incrementing the practice's `version` as well, and because a `DENIED` row counts as closed while a `SUBMITTED` one counts as open, the contract's `enrollment_open_count` rises off zero, incrementing the contract's `version` and re-firing its `LEGACY → PENDING_CREDENTIALING` edge if the contract had reverted. `submission_round` is what distinguishes the rounds.

`lead_days` is the whole-day gap between submission and the requested participation start: the difference between `effective_date` and `submitted_at` divided by 86,400 seconds, taking the floor. It is the credentialing lead time that decides whether a fee schedule may go live.

**Deciding** an enrollment requires `SUBMITTED` status and supplies a `decision` of either `APPROVE` or `DENY`. On `APPROVE` the enrollment moves `SUBMITTED → APPROVED`, `decided_at` is stamped from the logical clock, the practice's `pending_credentialing_count` decreases by one, the contract's `enrollment_open_count` decreases by one, the employment's credentialing dimension and the practice's posture are recomputed, and the `version` of the enrollment, of the practice and of the contract each increments by one. On `DENY` the request must also carry a non-empty `denial_reason`, and its absence is a payload failure reported as `ERR_INVALID_REQUEST`. The denial branch diverges sharply: the enrollment moves `SUBMITTED → DENIED` with `denial_reason` recorded and `decided_at` stamped, the practice's `pending_credentialing_count` decreases by one but its `denied_enrollment_count` increases by one, the contract's `enrollment_open_count` is left *unchanged*, the employment's credentialing dimension is pulled to `DENIED`, the recomputed posture carries the practice `STABILIZING → RESTRICTED`, and both the enrollment's and the practice's `version` increment by one. That posture demotion and its consequent block on fee-schedule activation are exactly what the approve branch does not do. `APPROVED` is terminal for an enrollment; a `SUSPENDED` enrollment is resumable only by a posture recompute and never by a client call, so acting on one is refused with `ERR_INVALID_ENROLLMENT_STATE`.

**Activating the DSO fee schedule** carries a contract `PENDING_CREDENTIALING → DSO_SCHEDULE_ACTIVE` and stores the contracted `dso_schedule_effective_date`. Its gates are evaluated in the order of §2.11: the contract must be `PENDING_CREDENTIALING`, so a contract already on the DSO schedule cannot be activated twice; the practice must be `AFFILIATED`; the practice's posture must be `STABILIZING` or `INTEGRATED`; `fee_schedule_item_count` must be at least one, or the request is refused with `ERR_FEE_SCHEDULE_EMPTY`; the contract must have at least one enrollment and every one of them must be `APPROVED`, or it is refused with `ERR_ENROLLMENTS_NOT_APPROVED`; every enrollment of the contract must show `lead_days` of at least 90 whole days, where exactly 90 passes and 89 fails with `ERR_CREDENTIALING_LEAD_TIME_SHORT`; and finally the materiality rule of §2.5 is applied, with `erosion_override_ack` recorded from the request and an omitted flag read as false. On success `blended_impact_cents` is recomputed and stored and the contract's `version` increments by one. Because the all-approved check sits above the lead-time check, a contract that is simultaneously un-credentialed and short on lead time reports the referential failure rather than the temporal one.

### 3.7. Vendor Consolidation, Clinician Preference Exceptions and Staffing Standardization

Consolidating an acquired practice onto the support organization's formulary saves money in theory and leaks money in practice, because clinicians keep the right to insist on the materials they trust. Both halves of that trade-off are modelled.

The integration lead **plans a consolidation** by naming the `practice_id`, the `vendor_category` of either `SUPPLY` or `LAB`, the legacy `baseline_annual_spend_cents` with incumbent vendors and the modelled `formulary_annual_spend_cents` on the DSO formulary (both zero or more). A plan opens in `PLANNED` with every savings figure empty and `exception_count_applied` at zero.

Meanwhile, a practising dentist may **request a preference exception** to the formulary, naming the `doctor_employment_id` the exception is filed against — which the server never compares to the requesting dentist's own doctor identity, so it need not be that dentist's own row — the `vendor_category` the exception applies to, the formulary or lab-service `item_code`, the `annual_qty` of the preferred item (at least one), the consolidated-vendor `formulary_unit_cents`, the clinician-preferred `preferred_unit_cents` (both zero or more) and a `clinical_rationale` justifying the departure. The requesting employment must be `ACTIVE`. The exception opens in `REQUESTED` with `incremental_cost_cents` empty.

Only the clinical director may **decide** an exception, which is the corporate-practice boundary at work: a preference for a particular material is a clinical determination, and no non-clinical role may make it. The decision requires, in the §2.11 order, that the underlying employment still be `ACTIVE` and then that the exception be `REQUESTED` — an exception already `APPROVED` or `DENIED` is refused with `ERR_INVALID_WORKFLOW_STATE` — and it supplies a `decision` of `APPROVE` or `DENY` plus an optional `decision_note`. On `APPROVE` the exception moves `REQUESTED → APPROVED` and `incremental_cost_cents` is stamped as the difference between `preferred_unit_cents` and `formulary_unit_cents` multiplied by `annual_qty`, which makes the exception eligible for consolidation leakage at the next finalization. On `DENY` the exception moves `REQUESTED → DENIED` and `incremental_cost_cents` is deliberately left empty so the exception can never enter leakage. Both branches stamp `decided_by_doctor_id` with the deciding director's own doctor identifier and increment the exception's `version` by one.

**Finalizing** a consolidation requires, in that order, the plan to be `PLANNED` — an already-`FINALIZED` plan is refused with `ERR_INVALID_WORKFLOW_STATE` — the practice to be `AFFILIATED` and the practice's posture to be `STABILIZING` or `INTEGRATED`. It computes three figures in order. First, gross savings: the difference between `baseline_annual_spend_cents` and `formulary_annual_spend_cents` is multiplied by the realization factor of 8,500 basis points — eighty-five percent, since not every modelled saving is actually captured — divided by ten thousand and rounded half up to whole cents, and stored as `gross_savings_cents`. Second, leakage, which is *not* discounted, because an approved exception is paid at full price from day one: every qualifying exception's `incremental_cost_cents` is summed in `created_at` ascending order into `exception_leakage_cents` with no rounding at all, and the number of exceptions folded in is stored as `exception_count_applied`. An exception qualifies only when its status is `APPROVED`, only when its employment sits at the same practice as the consolidation, and only when its `vendor_category` matches the consolidation's; `REQUESTED` and `DENIED` exceptions contribute nothing, and an approved exception in the other category or at another practice is excluded. Third, the net figure: `projected_savings_cents` is the greater of zero and `gross_savings_cents` less `exception_leakage_cents`, so leakage can erase savings but can never turn them into a reported loss. The plan then moves `PLANNED → FINALIZED` and its `version` increments by one.

**Standardizing staffing** is the integration lead's separate act on a practice, and it requires the practice to be `AFFILIATED` with a posture of `STABILIZING` or `INTEGRATED`. The request supplies the standardized hygienist-to-doctor `fte_hygiene_ratio_bps`, which must fall inside the inclusive band from 8,000 to 25,000 basis points — from 0.8 hygienist FTE per doctor up to 2.5 — where both 8,000 and 25,000 are accepted and anything outside is refused with `ERR_STAFFING_RATIO_OUT_OF_RANGE`. On success the ratio is stored, `staffing_model_state` moves `LEGACY → STANDARDIZED`, and the practice's `version` increments by one.

### 3.8. Clinical Quality and Treatment-Planning Oversight

Clinical quality review is where the support organization's boundary is most visible: the support organization funds the review, but a licensed clinical director alone opens it, scores it and closes it.

Opening a review names the `doctor_employment_id` under review — whose employment must be `ACTIVE` — and a `period_label` such as a quarter identifier, then reports the retrospective sample: `charts_sampled`, the charts pulled for review; `charts_with_findings`, the sampled charts carrying documentation or diagnostic findings; and `treatment_plan_overrides`, the sampled charts where the treatment plan was altered outside the treating clinician's judgement. The sample must clear a statistical floor of 20 charts, where exactly 20 is acceptable and 19 is refused with `ERR_SAMPLE_SIZE_TOO_SMALL`, and neither `charts_with_findings` nor `treatment_plan_overrides` may exceed `charts_sampled`, a violation of which is a payload failure reported as `ERR_INVALID_REQUEST`. The review opens in `OPEN` with no `closed_by_doctor_id` and no `outcome_note`.

The score is stamped at creation and re-stamped when the review is closed, and it is built from four independent roundings rather than one combined expression. `finding_rate_bps` is `charts_with_findings` multiplied by ten thousand and divided by `charts_sampled`, rounded half up. `override_rate_bps` is `treatment_plan_overrides` multiplied by ten thousand and divided by `charts_sampled`, rounded half up. The finding penalty is `finding_rate_bps` multiplied by the finding weight of 6,000 basis points — sixty percent of the total penalty weight — divided by ten thousand and rounded half up. The override penalty is `override_rate_bps` multiplied by the override weight of 4,000 basis points — the remaining forty percent — divided by ten thousand and rounded half up. `score_bps` is then the greater of zero and ten thousand less the finding penalty less the override penalty, so a perfect review scores exactly 10,000 basis points and a catastrophic one floors at zero rather than going negative.

Closing a review supplies an `outcome` and an optional `outcome_note`, and the outcome must be consistent with the stored score. Three outcomes exist. `CLOSED_NO_FINDINGS` is permitted only when `score_bps` is exactly 10,000. `CLOSED_WITH_PLAN` is permitted only when `score_bps` is at least the escalation threshold of 8,000 basis points, so a score of exactly 8,000 may close with a corrective plan while 7,999 may not. `ESCALATED` is always permitted, and it is mandatory whenever `score_bps` falls below 8,000. An outcome inconsistent with the score is refused with `ERR_QUALITY_OUTCOME_MISMATCH`.

Two clinical guards sit above that consistency check in the evaluation order of §2.11. The review must be `OPEN`, or the request is refused with `ERR_INVALID_WORKFLOW_STATE`. The closing director must hold a licence in the reviewed practice's own jurisdiction, per §2.12. And no clinician may sign off on the quality of their own charts: when the closing director's own doctor identity is the same doctor named by the reviewed employment, the close is refused with `ERR_SELF_REVIEW_PROHIBITED`. On a permitted close, the review moves from `OPEN` to `CLOSED_NO_FINDINGS`, `CLOSED_WITH_PLAN` or `ESCALATED` as requested, `closed_by_doctor_id` is stamped with the closing director's doctor identifier, `outcome_note` records the clinical narrative, and the review's `version` increments by one. All three closing outcomes are terminal.

### 3.9. The Earn-Out Pool: Projection, Reservation, Settlement and Claw-Back

The earn-out is measured against the deal's `baseline_ebitda_cents`, funded from the deal's `earnout_pool_cents`, and administered by finance controllers under strict segregation of duties. It is evaluated twice against the same tranche row, in two variants, and both evaluations must respect the conservation identity of §2.8.

A controller **projects** a measurement period by creating a tranche against an `affiliation_id`, giving it a `period_label` such as a first-earn-out-year identifier, and bounding it with `measurement_start` — the inclusive first instant — and `measurement_end` — the inclusive last instant — alongside the `expected_affiliation_version` guard of §2.9. Measurement periods of the same affiliation may abut but may never overlap: the requested half-open period is compared against every existing tranche of that affiliation whose status is not `CLAWED_BACK`, adjacency is allowed, and a genuine overlap is refused with `ERR_MEASUREMENT_PERIOD_OVERLAP`. A clawed-back tranche releases its period for reuse. A new tranche opens in `PROJECTED` with no `variant_applied`, with `reserved_cents`, `awarded_cents` and `clawed_back_cents` all at zero, with every reported, annualized, final and derived figure still empty, and with neither `reserved_by_user_id` nor `settled_by_user_id` recorded; it increments the affiliation's `version` by one.

**Reserving** the tranche runs the payout in its `PROVISIONAL` variant, because the measurement period is still running. Following the §2.11 order it requires first that the affiliation be `CLOSED` with an `earnout_measurement_state` of `OPEN` — a `SUSPENDED` measurement state, caused by any practice of the deal being frozen, blocks reservation with `ERR_INVALID_AFFILIATION_STATE` — and only then that the tranche be `PROJECTED`; it supplies the partial-period `reported_net_collections_cents` and `reported_expenses_cents`.

**Settling** the tranche runs the same eight steps in the `FINAL` variant against full-period figures. It requires the tranche to be `RESERVED` but carries no affiliation-status or `earnout_measurement_state` gate of its own, so a reserved tranche still settles while the deal's measurement window sits `SUSPENDED`; it supplies `final_net_collections_cents` and `final_expenses_cents`, and enforces segregation of duties: the settling `X-User-ID` must differ from the `reserved_by_user_id` recorded at reservation, and an identical user is refused with `ERR_SEGREGATION_OF_DUTIES`. Two distinct controller users are required even though both act in the single `DsoFinanceController` role.

The payout runs in eight pinned steps, and the order cannot be rearranged because the management fee rate is tiered on a figure produced earlier in the chain while the payout multiple is tiered on a figure produced two steps later.

**Step zero** selects the variant's inputs. In the `PROVISIONAL` variant the collections and expense inputs are `reported_net_collections_cents` and `reported_expenses_cents`, and the elapsed-day count is the whole days from `measurement_start` to the logical clock, taking the floor of the UTC difference; at least one whole day must have elapsed, so a reservation with zero or fewer elapsed days is refused with `ERR_MEASUREMENT_PERIOD_NOT_STARTED` rather than dividing by zero. In the `FINAL` variant the inputs are `final_net_collections_cents` and `final_expenses_cents`, and no elapsed-day count is needed.

**Step one** produces net collections, and this is the only genuinely variant-divergent arithmetic. Under `PROVISIONAL`, net collections are the reported collections multiplied by 365 days and divided by the elapsed-day count, rounded half up to whole cents, and `lag_holdback_cents` is zero. Under `FINAL`, `lag_holdback_cents` is first computed as the reported full-period collections multiplied by the claims-lag holdback of 250 basis points — two and a half percent — divided by ten thousand and rounded half up; net collections are then the full-period collections less that holdback. `annualized_net_collections_cents` is the annualized figure stored on the tranche by the provisional run.

**Step two** produces expenses. Under `PROVISIONAL` they are the reported expenses multiplied by 365 and divided by the same elapsed-day count, rounded half up, and stored as `annualized_expenses_cents`. Under `FINAL` the reported expenses are used unscaled with no rounding at all.

**Step three** selects the management fee rate from the step-one output. Net collections below 150,000,000 cents — one and a half million dollars a year — take a rate of 700 basis points, seven percent. Net collections at or above that but below 300,000,000 cents, three million dollars, take 600 basis points. Net collections at or above three million dollars take 550 basis points. Because the provisional variant feeds an *annualized* collections figure into this lookup, a partial period can land in a different fee tier than the same practice's full-year figures, which then shifts adjusted EBITDA, growth and the multiple downstream.

**Step four** computes `management_fee_cents` as net collections multiplied by the selected rate in basis points, divided by ten thousand, rounded half up to whole cents.

**Step five** computes `adjusted_ebitda_cents` as net collections less expenses less `management_fee_cents`, exactly, with no rounding.

**Step six** computes `growth_bps` as the difference between `adjusted_ebitda_cents` and the affiliation's `baseline_ebitda_cents`, multiplied by ten thousand and divided by that same baseline, rounded half up to whole basis points.

**Step seven** selects `multiple_bps` from the step-six output. Growth below zero takes a multiple of 0 basis points, so a tranche that measures below its baseline earns nothing. Growth at or above zero but below 800 basis points — eight percent — takes 25,000 basis points, a multiple of two and a half. Growth at or above eight percent but below 1,500 basis points — fifteen percent — takes 35,000 basis points, three and a half. Growth at or above fifteen percent takes 45,000 basis points, four and a half.

**Step eight** computes the raw payout as the difference between `adjusted_ebitda_cents` and `baseline_ebitda_cents`, multiplied by `multiple_bps` and divided by ten thousand, rounded half up to whole cents; the payout is then the greater of zero and that raw figure. Rounding occurs at steps one, two, four, six and eight and nowhere else.

Both operations then check the payout against the pool before writing anything. A reservation's payout must not exceed the affiliation's current `earnout_unallocated_cents`; a settlement's payout must not exceed `earnout_unallocated_cents` plus the reservation the settlement is about to release, that is the tranche's own `reserved_cents`. Either overage is refused with `ERR_EARNOUT_POOL_EXCEEDED`, leaving all four pool figures untouched.

On a successful reservation the tranche moves `PROJECTED → RESERVED`; `reported_net_collections_cents`, `reported_expenses_cents`, `annualized_net_collections_cents`, `annualized_expenses_cents`, `management_fee_cents`, `adjusted_ebitda_cents`, `growth_bps`, `multiple_bps` and a `lag_holdback_cents` of zero are all stamped, `variant_applied` is set to `PROVISIONAL`, `reserved_cents` is set to the computed payout and `reserved_by_user_id` records the acting user; the affiliation's `earnout_reserved_cents` rises by that amount and its `earnout_unallocated_cents` falls by exactly the same amount; and both the tranche's and the affiliation's `version` increment by one.

On a successful settlement the tranche moves `RESERVED → SETTLED`; `final_net_collections_cents`, `final_expenses_cents`, `lag_holdback_cents` and the recomputed `management_fee_cents`, `adjusted_ebitda_cents`, `growth_bps` and `multiple_bps` are all stamped, `variant_applied` becomes `FINAL`, `awarded_cents` is set to the final payout, `reserved_cents` is reset to zero and `settled_by_user_id` records the settling user; the affiliation's `earnout_reserved_cents` falls by the released reservation, its `earnout_settled_cents` rises by `awarded_cents`, and `earnout_unallocated_cents` is recomputed so the identity still holds exactly; and both versions increment by one.

**Clawing back** a settled tranche is the compensating operation of the whole fiscal chain. Following the §2.11 order it requires first that the affiliation be `CLOSED` and only then that the tranche be `SETTLED`, and it supplies a `clawback_reason`. `clawed_back_cents` is set to the current `awarded_cents`, which is then reset to zero; the affiliation's `earnout_settled_cents` falls by `clawed_back_cents` and its `earnout_unallocated_cents` rises by exactly the same amount, restoring the pool identity with zero drift; the tranche moves `SETTLED → CLAWED_BACK`, which is terminal; and both the tranche's and the affiliation's `version` increment by one.

## 4. Endpoint Definitions

Operations that mint a new resource return `201 Created`. Operations that modify an existing resource — every lifecycle transition, every decision, every recomputation and the logical-clock capability — return `200 OK`, as do all reads. Where the table names "All roles", every one of the five roles in §2.1 is authorized. The logical-clock capability is the one modifying operation that returns no resource: its envelope carries an empty object as `data`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dso/affiliations` | Open an affiliation transaction file for a target dental group | DsoDealCounsel |
| GET | `/dso/affiliations/{affiliation_id}` | Read one affiliation, including the three earn-out pool buckets | All roles |
| GET | `/dso/affiliations` | List affiliations with optional status filter and pagination | DsoDealCounsel, DsoIntegrationLead, DsoFinanceController |
| POST | `/dso/affiliations/{affiliation_id}/advance-diligence` | Move a DRAFT affiliation into DILIGENCE | DsoDealCounsel |
| POST | `/dso/affiliations/{affiliation_id}/reprice` | Reprice a deal in diligence, returning it to DRAFT for re-execution | DsoDealCounsel |
| POST | `/dso/affiliations/{affiliation_id}/sign` | Sign the affiliation agreement | DsoDealCounsel |
| POST | `/dso/affiliations/{affiliation_id}/close` | Close the transaction and run the five-hop post-close integration cascade | DsoIntegrationLead |
| POST | `/dso/conversion-vendors` | Register a practice-management-system conversion vendor and its crew capacity | DsoIntegrationLead |
| GET | `/dso/conversion-vendors/{conversion_vendor_id}` | Read one conversion vendor, including its live window count | DsoIntegrationLead, DsoDealCounsel, DsoFinanceController |
| POST | `/dso/practices` | Add a target practice to an affiliation and bind it to a conversion vendor | DsoDealCounsel, DsoIntegrationLead |
| GET | `/dso/practices/{practice_id}` | Read one practice, including the derived integration_posture and all integration counters | All roles |
| GET | `/dso/practices` | List practices, filterable by owning affiliation, conversion vendor or derived posture | DsoDealCounsel, DsoIntegrationLead, DsoFinanceController |
| POST | `/dso/practices/{practice_id}/standardize-staffing` | Adopt the DSO standard staffing model and hygiene FTE ratio at an integrated practice | DsoIntegrationLead |
| GET | `/dso/practices/{id}/vendor-consolidations` | List the supply and lab consolidation plans of one practice | DsoIntegrationLead, DsoFinanceController, ClinicalDirector |
| POST | `/dso/doctors` | Register a doctor with NPI and state licensure | DsoDealCounsel, DsoIntegrationLead |
| GET | `/dso/doctors/{doctor_id}` | Read one doctor record | All roles |
| POST | `/dso/doctor-employments` | Offer post-close employment terms, including the restrictive covenant, to a doctor at a practice | DsoIntegrationLead |
| GET | `/dso/doctor-employments/{doctor_employment_id}` | Read one employment row, including all three parallel state dimensions | All roles |
| GET | `/dso/doctor-employments` | List employment rows, filterable by practice, doctor or employment status | DsoDealCounsel, DsoIntegrationLead, DsoFinanceController, ClinicalDirector |
| POST | `/dso/doctor-employments/{doctor_employment_id}/accept-offer` | Doctor accepts the post-close employment offer; pre-close this only records acceptance, post-close it activates the employment immediately | Dentist |
| POST | `/dso/doctor-employments/{doctor_employment_id}/harmonize-compensation` | Harmonize a legacy compensation package onto the DSO model using the employment's comp_model variant | DsoFinanceController |
| POST | `/dso/doctor-employments/{doctor_employment_id}/separate` | Record a doctor departure and run the five-hop departure cascade | DsoIntegrationLead, Dentist |
| POST | `/dso/doctor-employments/{doctor_employment_id}/records-custody-transfer` | Transfer patient-records custody for a departed doctor | ClinicalDirector |
| POST | `/dso/doctor-employments/{doctor_employment_id}/enforce-non-compete` | Assert the restrictive covenant against a departed doctor | DsoDealCounsel |
| GET | `/dso/doctor-employments/{id}/supply-preference-exceptions` | List the clinician preference exceptions requested by one employed doctor | DsoIntegrationLead, DsoFinanceController, ClinicalDirector, Dentist |
| GET | `/dso/doctor-employments/{id}/clinical-quality-reviews` | List the clinical quality reviews of one employed doctor | DsoIntegrationLead, ClinicalDirector, Dentist |
| POST | `/dso/service-agreements` | Draft the non-clinical management services agreement for a practice | DsoDealCounsel |
| GET | `/dso/service-agreements/{service_agreement_id}` | Read one management services agreement | DsoDealCounsel, DsoIntegrationLead, DsoFinanceController |
| GET | `/dso/service-agreements` | List management services agreements, filterable by practice and status | DsoDealCounsel, DsoIntegrationLead, DsoFinanceController |
| POST | `/dso/service-agreements/{id}/line-items` | Add a non-clinical scope line to a draft agreement; clinical service domains are refused | DsoDealCounsel |
| GET | `/dso/service-agreements/{id}/line-items` | List the scope lines of one agreement | DsoDealCounsel, DsoIntegrationLead, DsoFinanceController, ClinicalDirector |
| POST | `/dso/service-agreements/{service_agreement_id}/submit-legal-review` | Submit the drafted scope for corporate-practice legal review | DsoDealCounsel |
| POST | `/dso/service-agreements/{service_agreement_id}/reject-scope` | Return an agreement to drafting with scope findings | DsoDealCounsel |
| POST | `/dso/service-agreements/{service_agreement_id}/make-effective` | Make the management services agreement effective | DsoDealCounsel |
| POST | `/dso/migration-batches` | Stage a chart-migration batch for a practice, superseding any earlier STAGED batch | DsoIntegrationLead |
| GET | `/dso/migration-batches/{migration_batch_id}` | Read one migration batch, including its cutover window and record ledger | DsoIntegrationLead, DsoDealCounsel, DsoFinanceController |
| GET | `/dso/migration-batches` | List migration batches, filterable by practice and status | DsoIntegrationLead, DsoDealCounsel, DsoFinanceController |
| POST | `/dso/migration-batches/{migration_batch_id}/schedule-cutover` | Reserve a conversion cutover window for a staged or remediated batch | DsoIntegrationLead |
| POST | `/dso/migration-batches/{migration_batch_id}/validate` | Report chart-validation results for a batch inside its cutover window | DsoIntegrationLead |
| POST | `/dso/migration-batches/{migration_batch_id}/remediate` | Return a quarantined batch to its reserved cutover window for another validation round | DsoIntegrationLead |
| POST | `/dso/migration-batches/{migration_batch_id}/rollback` | Roll back a validated batch, reversing its chart credit with zero drift | DsoIntegrationLead |
| POST | `/dso/migration-batches/{migration_batch_id}/reconcile` | Freeze a validated batch after final reconciliation | DsoIntegrationLead |
| POST | `/dso/payer-contracts` | Register a payer contract held by a practice | DsoFinanceController |
| GET | `/dso/payer-contracts/{payer_contract_id}` | Read one payer contract, including its blended fee-schedule impact | DsoFinanceController, DsoIntegrationLead, DsoDealCounsel |
| GET | `/dso/payer-contracts` | List payer contracts, filterable by practice and transition state | DsoFinanceController, DsoIntegrationLead, DsoDealCounsel |
| POST | `/dso/payer-contracts/{id}/fee-schedule-items` | Price one procedure on both the legacy and the DSO schedule | DsoFinanceController |
| GET | `/dso/payer-contracts/{id}/fee-schedule-items` | List the priced procedures of one payer contract with their stored line impacts | DsoFinanceController, DsoIntegrationLead, DsoDealCounsel |
| POST | `/dso/payer-contracts/{payer_contract_id}/activate-fee-schedule` | Move a credentialed contract onto the DSO fee schedule | DsoFinanceController |
| POST | `/dso/payer-enrollments` | Open a credentialing enrollment for one doctor on one payer contract | DsoIntegrationLead |
| GET | `/dso/payer-enrollments/{payer_enrollment_id}` | Read one credentialing enrollment, including its computed lead_days | DsoIntegrationLead, DsoFinanceController, DsoDealCounsel, ClinicalDirector |
| GET | `/dso/payer-enrollments` | List credentialing enrollments, filterable by payer contract, employment or status | DsoIntegrationLead, DsoFinanceController, DsoDealCounsel, ClinicalDirector |
| POST | `/dso/payer-enrollments/{payer_enrollment_id}/submit` | Submit or resubmit an enrollment to the payer | DsoIntegrationLead |
| POST | `/dso/payer-enrollments/{payer_enrollment_id}/decide` | Record the payer's credentialing decision | DsoIntegrationLead |
| POST | `/dso/earnout-tranches` | Project an earn-out measurement period against the affiliation's pool | DsoFinanceController |
| GET | `/dso/earnout-tranches/{earnout_tranche_id}` | Read one earn-out tranche, including which calculation variant was applied | DsoFinanceController, DsoDealCounsel, DsoIntegrationLead |
| GET | `/dso/earnout-tranches` | List earn-out tranches, filterable by affiliation and status | DsoFinanceController, DsoDealCounsel, DsoIntegrationLead |
| POST | `/dso/earnout-tranches/{earnout_tranche_id}/reserve` | Reserve the PROVISIONAL earn-out payout from partial-period figures | DsoFinanceController |
| POST | `/dso/earnout-tranches/{earnout_tranche_id}/settle` | Settle the tranche on FINAL full-period figures; must be performed by a different user than the reservation | DsoFinanceController |
| POST | `/dso/earnout-tranches/{earnout_tranche_id}/claw-back` | Claw back a settled tranche, returning the awarded cents to the unallocated pool | DsoFinanceController |
| POST | `/dso/supply-preference-exceptions` | A doctor requests a clinician-preference exception to the DSO supply or lab formulary | Dentist |
| GET | `/dso/supply-preference-exceptions/{supply_preference_exception_id}` | Read one clinician-preference exception | DsoIntegrationLead, DsoFinanceController, ClinicalDirector, Dentist |
| POST | `/dso/supply-preference-exceptions/{supply_preference_exception_id}/decide` | Clinical leadership approves or denies a preference exception | ClinicalDirector |
| POST | `/dso/vendor-consolidations` | Plan a supply or lab vendor consolidation for a practice | DsoIntegrationLead |
| GET | `/dso/vendor-consolidations/{vendor_consolidation_id}` | Read one consolidation plan, including gross savings, leakage and projected savings | DsoIntegrationLead, DsoFinanceController, ClinicalDirector |
| POST | `/dso/vendor-consolidations/{vendor_consolidation_id}/finalize` | Finalize the consolidation and book projected savings net of approved preference exceptions | DsoIntegrationLead |
| POST | `/dso/clinical-quality-reviews` | Open a clinical quality and treatment-planning review over a sample of one doctor's charts | ClinicalDirector |
| GET | `/dso/clinical-quality-reviews/{clinical_quality_review_id}` | Read one clinical quality review, including its weighted score | DsoIntegrationLead, ClinicalDirector, Dentist |
| POST | `/dso/clinical-quality-reviews/{clinical_quality_review_id}/close` | Close a quality review with an outcome consistent with its score, or escalate it | ClinicalDirector |
| POST | `/dso/_clock/set_current_utc` | Set the server's logical UTC clock; it starts at 2026-08-01T00:00:00Z and may only move forward or stay equal | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_AFFILIATION_NOT_FOUND` | 404 Not Found |
| `ERR_PRACTICE_NOT_FOUND` | 404 Not Found |
| `ERR_DOCTOR_NOT_FOUND` | 404 Not Found |
| `ERR_CONVERSION_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_DOCTOR_EMPLOYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_MIGRATION_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_PAYER_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_PAYER_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EARNOUT_TRANCHE_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLY_EXCEPTION_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_CONSOLIDATION_NOT_FOUND` | 404 Not Found |
| `ERR_QUALITY_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_AFFILIATION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PRACTICE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_AFFILIATION_STATE` | 409 Conflict |
| `ERR_INVALID_TRANCHE_STATE` | 409 Conflict |
| `ERR_INVALID_EMPLOYMENT_STATE` | 409 Conflict |
| `ERR_INVALID_BATCH_STATE` | 409 Conflict |
| `ERR_INVALID_ENROLLMENT_STATE` | 409 Conflict |
| `ERR_INVALID_AGREEMENT_STATE` | 409 Conflict |
| `ERR_INVALID_CONTRACT_STATE` | 409 Conflict |
| `ERR_INVALID_WORKFLOW_STATE` | 409 Conflict |
| `ERR_PRACTICE_NOT_AFFILIATED` | 409 Conflict |
| `ERR_PRACTICE_POSTURE_BLOCKED` | 409 Conflict |
| `ERR_LICENSE_STATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CORPORATE_PRACTICE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SELF_REVIEW_PROHIBITED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NON_COMPETE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_NO_TARGET_PRACTICE` | 422 Unprocessable Entity |
| `ERR_NO_POST_CLOSE_EMPLOYMENT` | 422 Unprocessable Entity |
| `ERR_SERVICE_AGREEMENT_NOT_EFFECTIVE` | 422 Unprocessable Entity |
| `ERR_SERVICE_SCOPE_EMPTY` | 422 Unprocessable Entity |
| `ERR_FEE_SCHEDULE_EMPTY` | 422 Unprocessable Entity |
| `ERR_ENROLLMENTS_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CUTOVER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_MEASUREMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CUTOVER_WINDOW_NOT_STARTED` | 409 Conflict |
| `ERR_CREDENTIALING_LEAD_TIME_SHORT` | 422 Unprocessable Entity |
| `ERR_MEASUREMENT_PERIOD_NOT_STARTED` | 422 Unprocessable Entity |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 Unprocessable Entity |
| `ERR_VENDOR_WINDOW_CAPACITY` | 409 Conflict |
| `ERR_QUARANTINE_COUNT_EXCEEDS_TOTAL` | 422 Unprocessable Entity |
| `ERR_SAMPLE_SIZE_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_NPI` | 409 Conflict |
| `ERR_DUPLICATE_PROCEDURE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_SERVICE_CODE` | 409 Conflict |
| `ERR_REPRICING_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_EARNOUT_POOL_LOCKED` | 409 Conflict |
| `ERR_QUALITY_OUTCOME_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STAFFING_RATIO_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_MGMT_FEE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FEE_EROSION_MATERIAL` | 422 Unprocessable Entity |
| `ERR_EARNOUT_POOL_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_COMP_HARMONIZATION_CAP_EXCEEDED` | 422 Unprocessable Entity |
