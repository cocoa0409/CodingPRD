# Hospital Price Transparency API — Product Requirements Document

## 1. Introduction

Federal price-transparency regulation obliges every hospital to publish its standard charges — gross chargemaster prices, discounted cash prices, and payer-specific negotiated rates — as a machine-readable file, and to maintain a consumer-facing shoppable-service display alongside it. Compliance is not a one-time export: files follow a monthly and annual publication cadence, payer contracts are renegotiated mid-year, reported discrepancies demand a corrected public record, and the Centers for Medicare & Medicaid Services (CMS) attests, rejects, and penalizes. This document specifies the Hospital Price Transparency API, the system of record a hospital's price-transparency office uses to run that entire obligation: extracting standard charges from contracts and rate schedules, assembling and validating the machine-readable file, certifying and publishing the shoppable-service list, and surviving the attestation-and-enforcement cycle that follows.

The design tension at the heart of the domain is confidentiality. Payer contracts routinely forbid disclosing exact negotiated minima, so the API derives a disclosable payer-specific figure under two divergent derivation variants, one of which deliberately obscures exact rates behind a volume-weighted blend and a de-identification payer floor. A second tension is correction without erasure: published figures are immutable snapshots, so errors are repaired by supersession — a lineage of charge records — rather than by editing history. Segregation of duties runs through the compliance surface: the operator who proposes a correction may not approve it, the approver may not apply it, and the compliance liaison who submits the CMS attestation never sits in the CMS decision chair. All transparency resources are mounted under the `/transparency` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, formats, and invariants that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `ContractManager`, `TransparencyOfficer`, `ComplianceAuditor`, and `Consumer`. A `PlatformAdmin` is the hospital-system platform operator: it registers facilities, drives the test-only logical clock, and acts as the CMS decision proxy. A `ContractManager` owns payer relations — payers, contracts, and negotiated rates. A `TransparencyOfficer` staffs the price-transparency office and owns service items, charge extraction, publication cycles, machine-readable files, shoppable lists, and the correction workflow. A `ComplianceAuditor` is the liaison to CMS: it submits attestations and corrective-action plans and triages discrepancy reports, and it is deliberately segregated from correction propose/approve/apply and from the CMS decision proxy. A `Consumer` is an anonymous public user of the shoppable display tool and discrepancy intake; it holds no exclusive write operations.

For all five roles — `PlatformAdmin`, `ContractManager`, `TransparencyOfficer`, `ComplianceAuditor`, and `Consumer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `proposed_by_user_id`, `approved_by_user_id`, or `applied_by_user_id` on a `DiscrepancyReport`, where the correction workflow writes it) but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in the system — `Facility`, `Payer`, `PayerContract`, `ServiceItem`, `StandardChargeRecord`, `PayerNegotiatedRate`, `ShoppableServiceList`, `PublicationCycle`, `MachineReadableFile`, and `DiscrepancyReport` — carries a common set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation time, and `updated_at` records the last modification time; both are ISO 8601 UTC timestamps with three fractional digits. The `version` is an integer that starts at its initial value on creation and increments by one on every mutation of the resource, including mutations delivered by a cascade rather than by a direct client write. All mutations and their cascades are applied atomically within the triggering request: the system never exposes a half-applied cascade.

### 2.5. The Logical Clock

Time-dependent behavior — contract expiry, penalty accrual, attestation escalation — is evaluated against a server-side logical clock, never against wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and before any explicit set it continues to read that default rather than falling back to wall-clock time. A `PlatformAdmin` may advance the clock through an admin-only test-driving capability mounted outside the transparency prefix, `POST /_clock/set_current_utc`, supplying a `to_iso8601` instant; the response reports the new `current_utc`. Advancing the clock is a system event with three scheduled consequences: every `ACTIVE` payer contract whose `effective_end` date now lies strictly before the new current date transitions to `EXPIRED` (firing the same rate cascade as a termination); every facility whose `attestation_status` is `REJECTED` and whose `plan_due_date` now lies strictly before the new clock transitions to `ESCALATED`; and `penalty_accrued_cents` is recomputed for every facility sitting in `REJECTED` or `ESCALATED`.

### 2.6. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency control; no other endpoint accepts a version field.

A request to update a `ServiceItem` must carry `expected_service_item_version`, holding the item `version` the client last observed. If another writer has advanced the item's version since that observation — for example by changing its gross charge or retiring it, both of which legitimately succeed under product semantics — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting an item state it has not seen.

A request to generate a `MachineReadableFile` must carry `expected_publication_cycle_version`, holding the cycle `version` the client last observed. If another writer has advanced the cycle's version since that observation — for example by generating a file for the same cycle (which legitimately supersedes the prior sealed file) or by adding or validating records — the generation is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Integer-Cents Arithmetic and Rounding Discipline

All monetary quantities are integer cents; the system never stores fractional cents. Where a percentage derivation produces a fraction — the percent-of-gross and percent-of-Medicare rate materializations, the volume-weighted disclosure mean, and the per-ancillary bundle discount — the result is truncated down to the next whole cent (floor semantics), at exactly the step the rule specifies. Two rounding placements are pinned. In rate materialization and in the weighted disclosure mean, the floor is applied once, to the final figure. In the shoppable bundle calculation, the ten-percent discount is floored per ancillary item first, and only then are the per-item contributions summed; the package total itself is never re-rounded. The alternative ordering — summing the ancillary gross amounts and flooring the discounted sum once — is forbidden, because it disagrees whenever per-item fractional remainders accumulate: two ancillary items priced at 333 cents each contribute 299 plus 299, a bundle sum of 598 cents, under the pinned order, whereas flooring ninety percent of the 666-cent sum would yield 599 cents.

### 2.8. The Rate-to-Publication Cascade Chain

Derived pricing flows down a fixed dependency chain, and mutations propagate back up it automatically, within the same request. A `ServiceItem`'s chargemaster figures feed its `PayerNegotiatedRate` rows; those rates, gated by their `PayerContract`'s status and confidentiality clause, feed the computed minima, maxima, and disclosure figures of each `StandardChargeRecord`; and records in a reportable state feed the aggregates of their `PublicationCycle`. Any event that perturbs one link recomputes every dependent link downstream — patching an item's price re-derives rates, records, and cycle aggregates; activating, renegotiating, terminating, or expiring a contract re-derives the same chain under a different rate inclusion set. Each recomputation is a real mutation: an affected cycle refreshes its `updated_at` and increments its `version`, as does every mutated rate, record, list, or file. Because the chain is also the optimistic-concurrency surface, clients holding a stale `version` of an item or cycle discover upstream movement through the rejection described in §2.6 rather than through silent drift.

### 2.9. Validation Order and Identifier Resolution

Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung. The ladder runs: first, the authentication headers of §2.1 (presence, then role permission); second, existence — every identifier in the URL path is resolved left to right, and then every foreign-key reference in the request body is resolved in the body's declared field order, with a missing resource producing the corresponding 404 (`ERR_FACILITY_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SERVICE_ITEM_NOT_FOUND`, `ERR_CHARGE_RECORD_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_SHOPPABLE_LIST_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, or `ERR_DISCREPANCY_NOT_FOUND`); third, state legality — the target resource must be in a status where the requested transition is defined (the 409 state errors); fourth, regulatory safety — segregation of duties, attestation-year alignment, and the consumer-display feature flag (`ERR_SOD_SAME_USER`, `ERR_ATTESTATION_YEAR_MISMATCH`, `ERR_DISPLAY_DISABLED`); fifth, structural constraints — duplicates, window overlaps, and entry composition rules; sixth, cross-referential coherence — the referenced records must belong to one another as the workflow requires; seventh, temporal sanity (`ERR_INVALID_WINDOW`); and last, fiscal and threshold rules. Consequently, a state error always masks a temporal error on the same request, and a missing resource always masks both.

## 3. Business Logic & Workflows

### 3.1. Facility Onboarding and Payer Contracting

A `PlatformAdmin` begins by registering each hospital facility, supplying its `name`, its CMS Certification Number in `cms_certification_number`, its licensed `bed_count`, and optionally its enforcement and certification posture: `penalty_policy` (`SIMPLE` or `TIERED`, defaulting to `SIMPLE`), `min_records_per_cycle` (defaulting to 1), `shoppable_min_entries` (defaulting to the CMS-required 300), `mandated_min_entries` (defaulting to the CMS-specified 70), and the consumer-display feature flag `shoppable_display_enabled` (defaulting to true). The certification number is unique across the platform; a duplicate registration is rejected with `ERR_DUPLICATE_CCN`. A new facility's `attestation_status` is `NONE`, its `attestation_year`, `attestation_cycle_id`, `rejected_at`, and `plan_due_date` are all null, and `penalty_accrued_cents` is zero.

A `ContractManager` then registers payer organizations with a `name`, a `payer_type` of `COMMERCIAL`, `MEDICARE_ADVANTAGE`, or `MEDICAID_MANAGED`, and a `confidentiality_tier` of `STANDARD` or `PROPRIETARY` (default `STANDARD`). The tier documents the payer's disclosure posture: a `PROPRIETARY` payer is one whose negotiated minima must never be disclosed exactly, which is precisely the guarantee the derivation variants of §3.3 are built to keep.

Each negotiated relationship becomes a `PayerContract`, created in `DRAFT` status with the contracting `facility_id` and `payer_id`, a `confidentiality_clause` of `DISCLOSE_ALLOWED`, `DERIVED_ONLY`, or `AGGREGATE_ONLY`, a projected `annual_volume` used later as the weight in weighted derivation, and a contract window from `effective_start` through `effective_end`. The contract window is a closed interval — both endpoints are inclusive — and `effective_start` must not fall after `effective_end`, or creation is rejected with `ERR_INVALID_WINDOW`.

### 3.2. The Service Catalog and Negotiated Rate Materialization

The transparency office's catalog is the `ServiceItem`. A `TransparencyOfficer` registers each billable service with its owning `facility_id`, a billing `code` (unique within the facility — a duplicate is rejected with `ERR_DUPLICATE_ITEM_CODE`), a `code_type` of `CPT`, `HCPCS`, `MS_DRG`, or `REVENUE_CODE`, a plain-language `description`, a `service_class` of `SHOPPABLE`, `ANCILLARY`, `SUPPLY`, `DRUG`, or `FACILITY_FEE`, the chargemaster price `gross_charge_cents` (zero or more), and optionally `medicare_base_cents` (zero or more, required in practice by percent-of-Medicare rates), an `ancillary_inclusion` posture of `ALWAYS_BUNDLED`, `CONDITIONALLY_INCLUDED`, or `SEPARATELY_PRICED` (default `SEPARATELY_PRICED`), and the `cms_shoppable_mandated` flag (default false) marking the CMS-specified shoppable services. New items are `ACTIVE`.

Negotiated rates live under contracts. A `ContractManager` creates a `PayerNegotiatedRate` by naming the `contract_id`, the `service_item_id`, and a `rate_type` of `PERCENT_OF_GROSS`, `FEE_SCHEDULE_FLAT`, or `PERCENT_OF_MEDICARE`. A `rate_percent` from 0 to 200 inclusive is required exactly when the type is `PERCENT_OF_GROSS` or `PERCENT_OF_MEDICARE`, and `flat_amount_cents` is required exactly when the type is `FEE_SCHEDULE_FLAT`; omitting the required input, or sending the wrong type or an unknown enum value anywhere in a payload, is rejected with `ERR_INVALID_REQUEST`. Naming a `RETIRED` item at rate creation — most pointedly for a `PERCENT_OF_MEDICARE` rate, whose materialization must read the retired item's `medicare_base_cents` — is rejected with `ERR_ITEM_RETIRED`. Rates may only be created while the owning contract is `DRAFT` or `RENEGOTIATING`; against any other contract status the attempt is rejected with `ERR_CONTRACT_NOT_EDITABLE`. Creating a rate for a contract-and-item pair that already has a `DRAFT` rate supersedes it: the prior draft moves `DRAFT → SUPERSEDED` and the new rate is born in `DRAFT`.

Every rate carries a materialized `negotiated_amount_cents`, recomputed on creation, on any rate amendment, and whenever the underlying item's `gross_charge_cents` or `medicare_base_cents` changes. The materialization reads the item's current field values — never a snapshot — and branches on the rate type. A `FEE_SCHEDULE_FLAT` rate materializes to its `flat_amount_cents` verbatim and is item-independent. A `PERCENT_OF_GROSS` rate materializes to the item's current `gross_charge_cents` multiplied by `rate_percent` and divided by 100, truncated down to a whole cent. A `PERCENT_OF_MEDICARE` rate materializes to the item's current `medicare_base_cents` multiplied by `rate_percent` and divided by 100, truncated down to a whole cent. A rate amendment — a `ContractManager` changing `rate_percent` or `flat_amount_cents` — is permitted only while the rate itself is `DRAFT`; amending a rate in any other status is rejected with `ERR_RATE_LOCKED`. The amendment recomputes `negotiated_amount_cents` and increments the rate's `version`, but it does not run the charge-record recompute cascade, because `DRAFT` rates are excluded from every record's input set to begin with.

### 3.3. Extracting Standard Charges into a Publication Cycle

Charge extraction collects one `StandardChargeRecord` per service item into an open cycle. A `PublicationCycle` is opened by a `TransparencyOfficer` with its `facility_id`, a `cycle_type` of `MONTHLY` or `ANNUAL`, a coverage window from `period_start` to `period_end`, and the CMS schema label `schema_version` (for example `v2.0.0`). Unlike contract windows, a cycle's coverage window is half-open — it includes `period_start` and excludes `period_end` — so `period_start` must fall strictly before `period_end`, otherwise creation is rejected with `ERR_INVALID_WINDOW`, and two cycles of the same facility and same `cycle_type` may not overlap unless one is terminal; windows that merely touch at an endpoint do not count as overlapping. An overlapping create is rejected with `ERR_CYCLE_PERIOD_OVERLAP`. A new cycle is `OPEN` with posture `COLLECTING`, and its aggregates `validated_record_count`, `total_gross_cents`, and `derived_rollup_cents` start at zero.

A `TransparencyOfficer` extracts a record by supplying the `facility_id`, the target `publication_cycle_id`, the `service_item_id`, the consumer-facing `discounted_cash_cents` (zero or more), and, only when this record is a correction replacement, an optional `supersedes_id`. The target cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`), the item must be `ACTIVE` (`ERR_ITEM_RETIRED`), and the three references must agree: the record's `facility_id` must match the facility of both its cycle and its item, or the create is rejected with `ERR_CROSS_FACILITY_REFERENCE`. When `supersedes_id` is present it must reference an existing record of the same facility whose status is `PUBLISHED` or `FLAGGED`; a missing, cross-facility, or wrongly-stated target is rejected with `ERR_SUPERSEDE_TARGET_INVALID`. The discounted cash price may never exceed the gross charge, at creation or later at validation, or the request fails with `ERR_CASH_EXCEEDS_GROSS`.

At creation the record snapshots the item's current `gross_charge_cents` and computes three derived figures. The universe considered is the facility's rates for the same item that are themselves `ACTIVE` and sit under a contract that is `ACTIVE`, belongs to the record's facility, and — for exact disclosure — carries the `DISCLOSE_ALLOWED` clause. Across that includible set, `min_negotiated_cents` is the smallest `negotiated_amount_cents` and `max_negotiated_cents` the largest; when the includible set is empty, both are null. Rates in `DRAFT`, `INACTIVE`, or `SUPERSEDED`, and rates under `DERIVED_ONLY` or `AGGREGATE_ONLY` contracts, never enter the extrema.

The disclosed payer-specific figure, `derived_disclosure_cents`, is produced together with a `derivation_method` of `EXACT_MIN`, `MIX_WEIGHTED`, or `NONE`, under a pinned evaluation order: first materialize every rate's `negotiated_amount_cents`; then partition the facility-and-item rate universe by confidentiality clause; then compute the de-identification payer count; then select the variant; then evaluate it. The payer count is the number of distinct payers whose `ACTIVE` contracts at this facility hold an `ACTIVE` rate for this item, and it never depends on the disclosure figure — there is no circularity. The de-identification floor is three distinct payers: a count of exactly three passes, a count of two fails. An `AGGREGATE_ONLY` contract's rate contributes only when that payer count meets the floor of three; otherwise it is excluded entirely. When no `DERIVED_ONLY` contract contributes and no includible `AGGREGATE_ONLY` contract contributes, the method is `EXACT_MIN` and `derived_disclosure_cents` is exactly `min_negotiated_cents` (null when the disclosable set is empty). Otherwise the method is `MIX_WEIGHTED`: the pool is the disclosable rates plus the `DERIVED_ONLY` rates plus any includible `AGGREGATE_ONLY` rates, and the figure is the volume-weighted mean — each rate's `negotiated_amount_cents` multiplied by its contract's `annual_volume`, those products summed, divided by the sum of the pool's `annual_volume` values, and truncated down to a whole cent. For identical rate data, the weighted variant deliberately produces a different number than the exact minimum whenever volumes and amounts differ. Should the weighted pool be empty, the method is recorded as `NONE` and `derived_disclosure_cents` is null. Creating the record also increments the cycle's `version`.

A record leaves `DRAFT` through validation. A `TransparencyOfficer` validates a record that is still `DRAFT` (`ERR_RECORD_NOT_DRAFT` otherwise) while its cycle remains `OPEN` (`ERR_CYCLE_NOT_OPEN`) and its item remains `ACTIVE` (`ERR_ITEM_RETIRED`). Validation additionally requires that at least one includible rate exists — a null `min_negotiated_cents` is rejected with `ERR_NO_NEGOTIATED_RATES` — and that `discounted_cash_cents` does not exceed `gross_charge_cents` (`ERR_CASH_EXCEEDS_GROSS`). On success the record transitions `DRAFT → VALIDATED`, both the record's and the cycle's `version` increment, and the cycle's aggregates recompute: `validated_record_count` counts the cycle's records in `VALIDATED`, `PUBLISHED`, or `FLAGGED`; `total_gross_cents` sums their `gross_charge_cents`; and `derived_rollup_cents` sums their `derived_disclosure_cents`, with records whose disclosure figure is null contributing zero.

### 3.4. Freezing, File Generation, and Publication

A cycle's posture is a derived, read-only signal computed from its own status and its children, recomputed on every mutation to the cycle or anything attached to it. While the cycle is `OPEN`, its `posture` is `FREEZABLE` when `validated_record_count` has reached the facility's `min_records_per_cycle` floor, and `COLLECTING` below it. Once `FROZEN`, the posture reflects the cycle's single sealed file — regeneration supersedes the prior sealed file, so at most one exists at a time: with no sealed file the posture is `AWAITING_FILE`; a sealed file whose `validation_status` is `UNVALIDATED` yields `FILE_UNVALIDATED`; `VALID` yields `PUBLISHABLE`; and `INVALID` yields `FILE_INVALID`. A `PUBLISHED` cycle's posture is `CURRENT`, and a `SUPERSEDED` cycle's posture is `ARCHIVED`.

Freezing moves a cycle `OPEN → FROZEN` and is gated on posture: the attempt is rejected with `ERR_POSTURE_NOT_FREEZABLE` whenever the cycle's posture is not `FREEZABLE`, which covers both an `OPEN` cycle still below its validated-record floor and a cycle that has already left `OPEN`. A successful freeze increments the cycle's `version` and recomputes posture.

Against a `FROZEN` cycle — anything else is rejected with `ERR_CYCLE_NOT_FROZEN` — a `TransparencyOfficer` generates the machine-readable file, choosing a `file_format` of `JSON` or `CSV` and passing `publication_cycle_id`; the OCC guard of §2.6 applies to this call. Generation serializes the cycle's `VALIDATED` records in ascending order of the service item's billing `code`, ties broken by the record's `created_at` ascending, and stamps the file with `record_count` (the number of records serialized) and `summary_total_discounted_cents` (the sum of those records' `discounted_cash_cents`). The file is a snapshot: later corrections never mutate a sealed or published file. The new file is born with `generation_status` `SEALED` and `validation_status` `UNVALIDATED`, the prior `SEALED` file of the same cycle — if any — cascades `SEALED → SUPERSEDED`, and the cycle's `version` increments.

Schema validation is a separate, repeatable step over a `SEALED` file; validating a file in any other generation status is rejected with `ERR_FILE_NOT_SEALED`. Validation evaluates three rules against live state at validate time, not generation time. If the file's `record_count` is below the facility's `min_records_per_cycle`, a `MIN_RECORDS_BELOW_FLOOR` violation is recorded. For every linked record in `VALIDATED` status whose service item has since been `RETIRED`, a `RETIRED_ITEM_PRESENT` violation tagged with the record's `id` is recorded. And for every linked `VALIDATED` record where an `ACTIVE` `AGGREGATE_ONLY` contract of the facility holds an `ACTIVE` rate for the record's item while the de-identification payer count for that item sits below three, a `DEIDENTIFICATION_VIOLATION` violation tagged with the record's `id` is recorded. The resulting `validation_errors` array is sorted for determinism by violation code ascending, ties broken by the record's `created_at` ascending. An empty violation list moves `validation_status` to `VALID` and clears `validation_errors`; a non-empty list moves it to `INVALID` and stores the codes. Re-validation loops — an `INVALID` file may be validated again after remediation, and either outcome may follow either prior state, provided the file remains `SEALED`. Each validation refreshes the owning cycle's posture and increments both the file's and the cycle's `version`.

Publishing moves a cycle `FROZEN → PUBLISHED` and is gated on posture the same way: a posture of exactly `PUBLISHABLE` is required — precisely one `SEALED` file exists and its `validation_status` is `VALID` — and any attempt whose posture falls short, including a cycle that is not `FROZEN` at all, is rejected with `ERR_POSTURE_NOT_PUBLISHABLE`. The publish cascade then runs in full: the cycle's `VALIDATED` records move `VALIDATED → PUBLISHED`; the sealed file moves `SEALED → PUBLISHED` on its generation dimension; and the previously published cycle of the same facility and same `cycle_type` — selected as the one with the latest `period_start`, ties broken by `created_at` ascending — moves `PUBLISHED → SUPERSEDED`, taking its `PUBLISHED` records to `SUPERSEDED` and its `PUBLISHED` files to `SUPERSEDED` with it. The newly published cycle's posture becomes `CURRENT`, the superseded cycle's becomes `ARCHIVED`, and every mutated resource increments its `version`.

### 3.5. The Shoppable Service List and Consumer Display

The consumer-facing artifact is the `ShoppableServiceList`, created by a `TransparencyOfficer` with a `facility_id`, a display `title`, and an `entries` array whose elements each name a `service_item_id`, a `display_name`, an optional list of `bundled_ancillary_item_ids`, an `include_conditional_ancillaries` boolean, and a `display_order` integer. Entry composition is policed at creation. Every entry's item must belong to the same facility, must not be `RETIRED` (`ERR_ITEM_RETIRED`), and must carry `service_class` `SHOPPABLE` (`ERR_ENTRY_NOT_SHOPPABLE`). Every item named in `bundled_ancillary_item_ids` must carry `service_class` `ANCILLARY` (`ERR_BUNDLED_ITEM_NOT_ANCILLARY`) and must not have an `ancillary_inclusion` of `SEPARATELY_PRICED` (`ERR_ANCILLARY_INCLUSION_VIOLATION`) — separately priced ancillaries can never ride inside a package. Two aggregates are computed at creation and refreshed as entries change: `entry_count` is the number of elements in `entries`, and `mandated_entry_count` counts the entries whose service item has `cms_shoppable_mandated` set.

Certification moves a list `DRAFT → CERTIFIED`. It requires `DRAFT` status (`ERR_LIST_NOT_DRAFT`) and then evaluates two threshold checks in a fixed order: the total-count check runs first, rejecting with `ERR_SHOPPABLE_COUNT_BELOW_MINIMUM` when `entry_count` falls below the facility's `shoppable_min_entries`; only when the total passes does the mandated-count check run, rejecting with `ERR_MANDATED_COUNT_BELOW_MINIMUM` when `mandated_entry_count` falls below the facility's `mandated_min_entries`. Both thresholds are inclusive — a count exactly equal to its floor passes.

Publishing moves a list `CERTIFIED → PUBLISHED`. A publish against a list in any other status is rejected with `ERR_LIST_NOT_CERTIFIED`. Two cross-entity gates then apply: the facility must have at least one `PUBLISHED` publication cycle (`ERR_NO_PUBLISHED_CYCLE`), and every entry's `service_item_id` must have a `PUBLISHED` charge record in the facility's latest `PUBLISHED` cycle (`ERR_ENTRY_RECORD_MISSING`). On success the list pins its evidence: `pinned_records` captures, for each entry's item, the charge record selected by facility match, item match, `PUBLISHED` status, and membership in the latest `PUBLISHED` cycle by `period_start` (ties broken by `created_at` ascending), storing the `charge_record_id` and the record's `version` at pin time as `record_version`. Any prior `PUBLISHED` list of the same facility auto-transitions `PUBLISHED → ARCHIVED`, and the new list's `version` increments.

The consumer display tool answers with the list's `list_id`, one computed row per entry, and a top-level `stale_any` flag. It is served only for a `PUBLISHED` list (`ERR_LIST_NOT_PUBLISHED`) and only while the facility's `shoppable_display_enabled` flag is on (`ERR_DISPLAY_DISABLED`). Each entry's `package_price_cents` is computed at read time from the pinned record — never the live record. The base price is the smallest of the pinned record's `gross_charge_cents`, its `discounted_cash_cents`, and, when it is not null, its `derived_disclosure_cents`. To that base the package adds each bundled ancillary's contribution, processed in ascending `display_order` with ties broken by the ancillary item's `created_at` ascending: an ancillary whose `ancillary_inclusion` is `ALWAYS_BUNDLED` always contributes, and one that is `CONDITIONALLY_INCLUDED` contributes only when the entry's `include_conditional_ancillaries` is set. Each contribution is the ancillary's live `gross_charge_cents` discounted by ten percent — ninety percent of the gross charge, floored per item to a whole cent — and then summed, per the pinned rounding order of §2.7. Each entry also carries a `stale` flag, set when the pinned record's current `version` no longer equals the pinned `record_version`, or when the pinned record has since moved to `SUPERSEDED`; `stale_any` is true when any entry is stale.

### 3.6. Attestation, CMS Decisions, and Civil Monetary Penalties

Once a year a `ComplianceAuditor` submits the facility's attestation of compliance, supplying the `attestation_year`. Submission is defined from `NONE` and from `CLOSED`, and from anywhere else is rejected with `ERR_ATTESTATION_INVALID_STATE`. The supplied year must equal the calendar year of the current logical clock (`ERR_ATTESTATION_YEAR_MISMATCH`), and a resubmission from `CLOSED` must name a year different from the facility's previous `attestation_year`. The attestation must rest on evidence: the facility must have an `ANNUAL` cycle in `PUBLISHED` status whose half-open coverage window fully contains the attestation calendar year — from January 1 through December 31 of `attestation_year` — or submission is rejected with `ERR_NO_CONTAINING_ANNUAL_CYCLE`. On success the facility moves to `SUBMITTED`, records the year in `attestation_year`, and pins `attestation_cycle_id` to the containing cycle, selecting among matches the one with the latest `period_start`, ties broken by `created_at` ascending. A resubmission from `CLOSED` additionally clears `rejected_at` and `plan_due_date` to null. Every attestation transition increments the facility's `version`.

The CMS decision arrives through a `PlatformAdmin` acting as the decision proxy, supplying a `decision` of `ACCEPT_ATTESTATION`, `REJECT_ATTESTATION`, `ACCEPT_PLAN`, or `REJECT_PLAN`, and, for the two rejection flavors, a `plan_due_date` that must fall strictly after the current clock (`ERR_INVALID_WINDOW`). Each decision is defined only from one attestation status, and any other pairing is rejected with `ERR_ATTESTATION_INVALID_STATE`. `ACCEPT_ATTESTATION` applies from `SUBMITTED` and moves the facility to `ACCEPTED`; penalty accrual stops, and `rejected_at` remains null. `REJECT_ATTESTATION` also applies from `SUBMITTED` and moves the facility to `REJECTED`, stamping `rejected_at` with the current logical clock and storing the supplied `plan_due_date`; in the same request, every `PUBLISHED` machine-readable file of the pinned `attestation_cycle_id` cycle is retracted, moving `PUBLISHED → RETRACTED` on its generation dimension.

While the facility sits in `REJECTED`, two things happen. If the logical clock advances strictly past `plan_due_date` before a plan arrives, the system moves the facility `REJECTED → ESCALATED`, where penalties keep accruing. Independently, a `ComplianceAuditor` may submit a corrective-action plan carrying its `plan_text`, moving the facility from `REJECTED` or `ESCALATED` to `PLAN_SUBMITTED` (any other attestation status is again `ERR_ATTESTATION_INVALID_STATE`). CMS then decides the plan: `ACCEPT_PLAN` applies from `PLAN_SUBMITTED` and moves the facility to `CLOSED`, freezing `penalty_accrued_cents` at its current value; `REJECT_PLAN` applies from `PLAN_SUBMITTED`, returns the facility to `REJECTED`, stores the new `plan_due_date`, and — critically — leaves `rejected_at` untouched, so accrual continues from the original rejection rather than restarting. The lifecycle is perennial: from `CLOSED`, next year's submission loops the facility back to `SUBMITTED`.

The civil monetary penalty, `penalty_accrued_cents`, is computed on every read of the facility and recomputed on every clock advance, but only while `attestation_status` is `REJECTED` or `ESCALATED`; in any other status the figure is frozen at its last computed value — zero if the facility was never rejected, and a rejection after `CLOSED` restarts from zero because `rejected_at` is stamped anew. The elapsed time is the number of whole days between `rejected_at` and the current logical clock — the elapsed seconds divided by the 86,400 seconds of a full day, truncated down, and never negative. Under the `SIMPLE` penalty policy the accrual is a flat 30000 cents (300 dollars) per elapsed day regardless of size. Under the `TIERED` policy the daily rate is bracketed by `bed_count`: 10000 cents (100 dollars) per day at 30 beds or fewer, 20000 cents (200 dollars) per day from 31 through 199 beds, and 40000 cents (400 dollars) per day at 200 beds or more. The variants diverge materially: a 25-bed facility three days into rejection accrues 30000 cents under `TIERED` but 90000 cents under `SIMPLE`.

### 3.7. Discrepancy Intake and the Segregated Correction Pipeline

Anyone — including an anonymous `Consumer` — may report a discrepancy against published data by supplying the `publication_cycle_id`, the disputed `standard_charge_record_id`, a `reporter_type` of `CONSUMER`, `PAYER`, or `INTERNAL`, and a free-text `description`. The referenced cycle must be `PUBLISHED` (`ERR_CYCLE_NOT_PUBLISHED`). Two referential checks then run in a fixed order: first the disputed record must belong to the referenced cycle (`ERR_RECORD_CYCLE_MISMATCH`), and only then is the record's disputable status checked — it must be `PUBLISHED` or `FLAGGED`, otherwise the report is rejected with `ERR_RECORD_NOT_DISPUTABLE`. A new report is `SUBMITTED`.

A `ComplianceAuditor` triages a `SUBMITTED` report with an `outcome` of `CONFIRMED` or `DISMISSED`; triage from any other status, and indeed any correction action attempted from a status where it is not defined, is rejected with `ERR_DISCREPANCY_NOT_ACTIONABLE`. A `DISMISSED` outcome simply closes the report. A `CONFIRMED` outcome moves the report `SUBMITTED → CONFIRMED` and, in the same request, moves the disputed record `PUBLISHED → FLAGGED`, incrementing the record's `version` — the public file itself is a snapshot and is not rewritten, but the flag marks the record as disputed wherever computed views consult it.

Correction is a three-chair workflow enforced by segregation of duties. A `TransparencyOfficer` proposes corrected figures on a `CONFIRMED` report, supplying at least one of `proposed_gross_charge_cents` or `proposed_discounted_cash_cents`; a payload with neither is a no-op and is rejected with `ERR_INVALID_REQUEST`. The effective proposed discounted cash price must not exceed the effective proposed gross charge — a supplied proposal overrides the record's current value on its side, and a side left unsupplied falls back to the record's current value — or the proposal is rejected with `ERR_CASH_EXCEEDS_GROSS`. A successful proposal moves the report `CONFIRMED → CORRECTION_PROPOSED` and stamps `proposed_by_user_id` with the acting `X-User-ID`. Approval moves the report `CORRECTION_PROPOSED → CORRECTION_APPROVED` and stamps `approved_by_user_id`, but the approver must not be the proposer: an `X-User-ID` equal to `proposed_by_user_id` is rejected with `ERR_SOD_SAME_USER`. Application moves the report `CORRECTION_APPROVED → CORRECTED` and stamps `applied_by_user_id`, and likewise the applier must not be the approver, on pain of `ERR_SOD_SAME_USER`.

Application is the moment the public record changes. The disputed record moves `FLAGGED → SUPERSEDED`, and a brand-new `StandardChargeRecord` is created directly in `PUBLISHED` status with `supersedes_id` pointing at the disputed record, its `gross_charge_cents` set to `proposed_gross_charge_cents` when present and to the prior value otherwise, its `discounted_cash_cents` set to `proposed_discounted_cash_cents` when present and to the prior value otherwise, and its minima, maxima, and disclosure figure recomputed. The owning cycle's aggregates adjust surgically in the same request: `validated_record_count` is conserved — the old record leaves the counted set as the new one enters — `total_gross_cents` shifts by exactly the difference between the new and old gross charges, and `derived_rollup_cents` recomputes; the cycle's `version` increments, as do the discrepancy's and both records'.

### 3.8. Contract Lifecycle Events and Price Maintenance Cascades

Contracts move through `DRAFT → ACTIVE → RENEGOTIATING → ACTIVE`, with `TERMINATED` and `EXPIRED` as terminal states, and every move ripples down the cascade chain of §2.8. Activation is defined from `DRAFT` and from `RENEGOTIATING`; attempting it — or renegotiation or termination — from `TERMINATED` or `EXPIRED`, or attempting renegotiation or termination from anything but `ACTIVE`, is rejected with `ERR_CONTRACT_ALREADY_TERMINAL`. Activation re-checks the window (`effective_start` must not fall after `effective_end`, else `ERR_INVALID_WINDOW`) and enforces single active coverage: no other `ACTIVE` contract may exist for the same `facility_id` and `payer_id` whose closed window intersects this one, and because contract windows are closed intervals, windows that touch at an endpoint count as intersecting; a violation is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`. A successful activation fires three cascade links in one request: the contract's `DRAFT` rates move to `ACTIVE` and recompute their `negotiated_amount_cents`; every `DRAFT` or `VALIDATED` charge record of the same facility touching items covered by those rates recomputes its minima, maxima, and disclosure figure; and every affected cycle recomputes `derived_rollup_cents` and increments its `version`.

Renegotiation moves an `ACTIVE` contract to `RENEGOTIATING`, optionally applying a new `effective_end` or a new `confidentiality_clause` from the request, and fires the mirror cascade: the contract's `ACTIVE` rates return to `DRAFT` so they can be edited again, affected records recompute with those draft rates now excluded from their input sets, and affected cycles recompute and increment. Termination moves an `ACTIVE` contract to `TERMINATED` and drives its `ACTIVE` rates to `INACTIVE`, with the same record-and-cycle recompute under the reduced inclusion set. Expiry is the system's own version of termination: when the logical clock advances past a contract's `effective_end` — the current date strictly after the window's inclusive end — the contract moves `ACTIVE → EXPIRED` and fires the identical cascade. Rate states therefore mirror their contract's lifecycle without any direct write to the rate: drafts activate with the contract, actives return to draft on renegotiation, and actives go inactive on termination or expiry; only the create-with-supersede of §3.2 moves a rate on its own.

Price maintenance on the catalog runs through the OCC-guarded item update of §2.6. A `TransparencyOfficer` may patch an item's `gross_charge_cents` or `medicare_base_cents` while passing `expected_service_item_version`; the change increments the item's `version` and fires the cascade in full — the item's `DRAFT` and `ACTIVE` rates recompute their materialized amounts, the facility's `DRAFT` and `VALIDATED` records for that item recompute their extrema and disclosure figures, and affected cycles recompute `derived_rollup_cents` and increment. The same endpoint retires the item: passing a `status` of `RETIRED` moves the item `ACTIVE → RETIRED`, provided no `CERTIFIED` or `PUBLISHED` shoppable list of the same facility still references the item in an entry — a guarded retirement that fails with `ERR_ITEM_IN_CERTIFIED_LIST`. Retirement is terminal, and a retired item reverberates through the rest of the workflow: it blocks record creation and validation (`ERR_ITEM_RETIRED`), and it surfaces during file validation as a `RETIRED_ITEM_PRESENT` violation.

## 4. Endpoint Definitions

Operations that create a new resource — registering a facility, payer, contract, service item, charge record, rate, shoppable list, publication cycle, machine-readable file, or discrepancy report — return `201 Created`. Operations that read, modify, or transition an existing resource, and the clock-advance capability, return `200 OK`. All other response details follow §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server logical clock | PlatformAdmin |
| POST | `/transparency/facilities` | Register a facility subject to price transparency | PlatformAdmin |
| GET | `/transparency/facilities/{id}` | Read a facility incl. attestation posture and accrued penalty | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| POST | `/transparency/facilities/{id}/submit-attestation` | Submit the annual CMS attestation | ComplianceAuditor |
| POST | `/transparency/facilities/{id}/cms-decision` | CMS decision proxy: accept/reject attestation or corrective plan | PlatformAdmin |
| POST | `/transparency/facilities/{id}/submit-plan` | Submit a corrective-action plan after rejection | ComplianceAuditor |
| POST | `/transparency/payers` | Register a payer organization | ContractManager |
| GET | `/transparency/payers/{id}` | Read a payer | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| GET | `/transparency/payers/{id}/payer-contracts` | List contracts of a payer | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| POST | `/transparency/payer-contracts` | Create a payer contract in DRAFT | ContractManager |
| GET | `/transparency/facilities/{id}/payer-contracts` | List contracts of a facility | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| POST | `/transparency/payer-contracts/{id}/activate` | Activate a DRAFT or RENEGOTIATING contract | ContractManager |
| POST | `/transparency/payer-contracts/{id}/renegotiate` | Move an ACTIVE contract to RENEGOTIATING, optionally amending window/clause | ContractManager |
| POST | `/transparency/payer-contracts/{id}/terminate` | Terminate an ACTIVE contract | ContractManager |
| POST | `/transparency/service-items` | Register a billable service item | TransparencyOfficer |
| GET | `/transparency/facilities/{id}/service-items` | List service items of a facility | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| PATCH | `/transparency/service-items/{id}` | Update gross/Medicare base price or retire the item (OCC-guarded) | TransparencyOfficer |
| POST | `/transparency/standard-charge-records` | Extract a standard charge record into an OPEN cycle | TransparencyOfficer |
| GET | `/transparency/standard-charge-records/{id}` | Read a charge record | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| GET | `/transparency/standard-charge-records` | List/filter charge records by facility, cycle, item, supersedes target, or status | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| POST | `/transparency/standard-charge-records/{id}/validate` | Validate a DRAFT charge record | TransparencyOfficer |
| POST | `/transparency/payer-negotiated-rates` | Create a negotiated rate under a DRAFT/RENEGOTIATING contract | ContractManager |
| GET | `/transparency/payer-negotiated-rates/{id}` | Read a negotiated rate | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| GET | `/transparency/payer-negotiated-rates` | List/filter rates by contract, item, or status | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| PATCH | `/transparency/payer-negotiated-rates/{id}` | Amend a DRAFT rate's percent or flat amount | ContractManager |
| POST | `/transparency/shoppable-service-lists` | Create a shoppable-service list with embedded entries | TransparencyOfficer |
| GET | `/transparency/facilities/{id}/shoppable-service-lists` | List shoppable lists of a facility | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| POST | `/transparency/shoppable-service-lists/{id}/certify` | Certify a DRAFT list against count thresholds | TransparencyOfficer |
| POST | `/transparency/shoppable-service-lists/{id}/publish` | Publish a CERTIFIED list, pinning charge-record versions | TransparencyOfficer |
| GET | `/transparency/shoppable-service-lists/{id}/display` | Consumer display: per-entry package prices with staleness flags | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| POST | `/transparency/publication-cycles` | Open a monthly/annual publication cycle | TransparencyOfficer |
| GET | `/transparency/publication-cycles/{id}` | Read a cycle incl. posture and aggregates | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| GET | `/transparency/facilities/{id}/publication-cycles` | List cycles of a facility | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| POST | `/transparency/publication-cycles/{id}/freeze` | Freeze an OPEN cycle (posture gate) | TransparencyOfficer |
| POST | `/transparency/publication-cycles/{id}/publish` | Publish a FROZEN cycle, superseding the prior published cycle | TransparencyOfficer |
| POST | `/transparency/machine-readable-files` | Generate (seal) a machine-readable file for a FROZEN cycle (OCC-guarded) | TransparencyOfficer |
| GET | `/transparency/publication-cycles/{id}/machine-readable-files` | List files of a cycle | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| POST | `/transparency/machine-readable-files/{id}/validate` | Run schema validation over a SEALED file | TransparencyOfficer |
| POST | `/transparency/discrepancy-reports` | Report a discrepancy against a PUBLISHED cycle's record | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| GET | `/transparency/discrepancy-reports/{id}` | Read a discrepancy report | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| GET | `/transparency/discrepancy-reports` | List/filter discrepancy reports | PlatformAdmin, TransparencyOfficer, ContractManager, ComplianceAuditor, Consumer |
| POST | `/transparency/discrepancy-reports/{id}/triage` | Triage a SUBMITTED report (confirm or dismiss) | ComplianceAuditor |
| POST | `/transparency/discrepancy-reports/{id}/propose-correction` | Propose corrected values for a CONFIRMED discrepancy | TransparencyOfficer |
| POST | `/transparency/discrepancy-reports/{id}/approve-correction` | Approve a proposed correction (segregated from proposer) | TransparencyOfficer |
| POST | `/transparency/discrepancy-reports/{id}/apply-correction` | Apply an approved correction (segregated from approver) | TransparencyOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_PAYER_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGE_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_RATE_NOT_FOUND` | 404 Not Found |
| `ERR_SHOPPABLE_LIST_NOT_FOUND` | 404 Not Found |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_FILE_NOT_FOUND` | 404 Not Found |
| `ERR_DISCREPANCY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CONTRACT_NOT_EDITABLE` | 409 Conflict |
| `ERR_CONTRACT_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_CYCLE_NOT_OPEN` | 409 Conflict |
| `ERR_CYCLE_NOT_FROZEN` | 409 Conflict |
| `ERR_CYCLE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_RATE_LOCKED` | 409 Conflict |
| `ERR_ITEM_RETIRED` | 409 Conflict |
| `ERR_RECORD_NOT_DRAFT` | 409 Conflict |
| `ERR_LIST_NOT_DRAFT` | 409 Conflict |
| `ERR_LIST_NOT_CERTIFIED` | 409 Conflict |
| `ERR_LIST_NOT_PUBLISHED` | 409 Conflict |
| `ERR_DISCREPANCY_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_ATTESTATION_INVALID_STATE` | 409 Conflict |
| `ERR_FILE_NOT_SEALED` | 409 Conflict |
| `ERR_POSTURE_NOT_FREEZABLE` | 409 Conflict |
| `ERR_POSTURE_NOT_PUBLISHABLE` | 409 Conflict |
| `ERR_SOD_SAME_USER` | 422 Unprocessable Entity |
| `ERR_ATTESTATION_YEAR_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DISPLAY_DISABLED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CCN` | 409 Conflict |
| `ERR_DUPLICATE_ITEM_CODE` | 409 Conflict |
| `ERR_CONTRACT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CYCLE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_ENTRY_NOT_SHOPPABLE` | 422 Unprocessable Entity |
| `ERR_BUNDLED_ITEM_NOT_ANCILLARY` | 422 Unprocessable Entity |
| `ERR_ANCILLARY_INCLUSION_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CROSS_FACILITY_REFERENCE` | 422 Unprocessable Entity |
| `ERR_RECORD_CYCLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RECORD_NOT_DISPUTABLE` | 422 Unprocessable Entity |
| `ERR_SUPERSEDE_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_SHOPPABLE_COUNT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_MANDATED_COUNT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_CASH_EXCEEDS_GROSS` | 422 Unprocessable Entity |
| `ERR_NO_NEGOTIATED_RATES` | 422 Unprocessable Entity |
| `ERR_NO_CONTAINING_ANNUAL_CYCLE` | 422 Unprocessable Entity |
| `ERR_NO_PUBLISHED_CYCLE` | 422 Unprocessable Entity |
| `ERR_ITEM_IN_CERTIFIED_LIST` | 409 Conflict |
| `ERR_ENTRY_RECORD_MISSING` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
