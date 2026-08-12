# Property Restoration Estimating API — Product Requirements Document

## 1. Introduction

Property restoration contractors live in a three-way negotiation: they document a loss on the insured's property, price the repair in the carrier's own category-and-line format, and then defend every line against the carrier's adjuster — all while supplements for discovered damage, building-code upgrades, depreciation holdbacks, and deductible collection move money back and forth. When any one of those threads is tracked in a spreadsheet or an inbox, the ledger stops reconciling and either the contractor or the policyholder absorbs the difference.

This document specifies the Property Restoration Estimating & Insurance Repair API, the system of record for that workflow. It covers loss assessment with photo and moisture evidence, estimate preparation with carrier-standard line-item pricing, adjuster negotiation rounds with deemed-acceptance expiry, supplement submission with scope-drift protection, ordinance & law code-upgrade coverage allocation, work authorization with direct-pay assignment, depreciation recovery at final invoice, and customer deductible collection. The API enforces a strict segregation of duties between contractor staff, the carrier adjuster, and the insured customer; keeps every claim-level money aggregate derived and immediately consistent; and drives all time-dependent behavior from a single logical clock. All endpoints are mounted under the `/v1` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every resource and endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. If either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401). If the caller's role is not in the endpoint's authorized role list, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The system recognizes five roles:

- `ContractorAdmin` — the restoration contractor's back office: configures carriers and price lists, onboards customers, policies, and claims, drives work execution, invoices, and clears money.
- `Estimator` — the contractor's estimator: builds and negotiates estimates, files supplements and code upgrades.
- `FieldTechnician` — the field inspector: performs loss assessments, moisture readings, and photo documentation.
- `Adjuster` — the carrier adjuster: reviews and negotiates estimates, approves supplements and code upgrades, and approves and issues carrier-direction payments.
- `Customer` — the insured property owner: signs work authorizations and pays the deductible; reads their own claim data.

When `X-User-Role` is `ContractorAdmin`, `Estimator`, `FieldTechnician`, or `Adjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on an `Invoice` when the invoice is created) but does not compare it to any entity's `id`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. A `Customer` caller touching a claim-scoped resource whose owning claim's `customer_id` does not equal `X-User-ID` receives `ERR_RESOURCE_NOT_FOUND` (HTTP 404) — the resource is treated as non-existent rather than forbidden.

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

Requests that fail before or outside normal routing are still answered in this envelope: an unknown path is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), a wrong method on a known path with `ERR_RESOURCE_NOT_FOUND` at HTTP 405, a request the framework itself cannot parse with `ERR_INVALID_REQUEST` (HTTP 400), and an unexpected internal failure with `ERR_INVALID_REQUEST` at HTTP 500.

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order — this includes the payments of a claim, which are likewise ordered `created_at` ascending — with ties on `created_at` broken by insertion order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

Most list endpoints also accept optional equality filters drawn from the resource's own fields — for example, claims filter by `policy_id`, `customer_id`, or `status`; price list entries by `category_code`; policies by `customer_id` or `carrier_id`; photos by `claim_id`, `inspection_id`, `supplement_id`, or `tag`; moisture readings by `area`; estimates by `status` or `type`; estimate lines by `negotiation_status`; payments by `type` or `status`; and inspections, negotiation rounds, dispositions, supplements, code upgrades, work authorizations, and invoices by `status`.

### 2.4. The Logical Clock and Time-Driven Sweeps

All time in the system is governed by a single logical clock; no behavior anywhere in the API depends on the wall clock. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z. A `ContractorAdmin` may advance it through a test-driving capability that takes a target instant `to_iso8601` and returns the resulting `current_utc` together with `expired_round_ids`, the identifiers of any negotiation rounds the advance expired, listed in the rounds' creation order. Every system-stamped timestamp in this document — `submitted_at`, `approved_at`, `completed_at`, `signed_at`, `issued_at`, `voided_at`, `decided_at` — is read from this logical clock. Datetime inputs everywhere are ISO 8601, and an input without a zone offset is interpreted as UTC. Logical-clock stamps (including `current_utc` and stored windows such as `effective_from`, `period_start`, `scheduled_start`, `due_at`, and `expires_at`) render with a `Z` suffix and carry fractional seconds only when the instant has sub-second precision — unlike `created_at` and `updated_at` (§2.5), which always carry three fractional digits.

Advancing the clock is not inert. When the clock passes an `OPEN` negotiation round's `due_at`, the expiry sweep fires and settles the round by deemed acceptance, as described in §3.5. The clock also decides whether a signed work authorization is still within its validity window when work starts (§3.8).

### 2.5. Common Resource Properties

Every resource in this API — carriers, price list entries, customers, policies, claims, inspections, moisture readings, photos, estimates, estimate lines, supplements, negotiation rounds, line dispositions, code upgrades, work authorizations, invoices, and payments — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; refreshed on every change.
- `version` (integer): a system-managed integer that increments by 1 on every mutation of the resource, including mutations caused by cascading side effects (for example, creating an estimate increments the parent claim's `version`, and editing a line increments the estimate's `version`). One exception: pure recomputation of a derived aggregate — an estimate's totals, the claim's money totals and ledger counters, `ordinance_consumed_cents`, a round's `disputed_amount_cents` — refreshes `updated_at` without by itself incrementing `version`; any accompanying substantive change or transition still increments it.

### 2.6. Reference Resolution and Nested Retrieval

Identifiers appearing in a URL path are validated in strict left-to-right order: the first identifier that does not resolve to an existing resource rejects the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), before any later identifier or any business rule is examined. The same error and status apply when a body-supplied reference does not resolve — a `policy_id` on claim creation, a `price_list_entry_id` on a new estimate line, a `claim_id` on a photo, an `inspection_id` or `supplement_id` on a photo or reading, or an `estimate_line_id` inside a negotiation disposition. As stated in §2.1, `Customer`-role access to a resource outside the caller's ownership also surfaces as `ERR_RESOURCE_NOT_FOUND`.

### 2.7. Validation Discipline and Priority Ordering

When a request would fail several checks, the failure that surfaces is determined by a fixed priority order, evaluated highest-first:

1. **Authentication context** — presence of `X-User-ID` / `X-User-Role` and a declared role value (`ERR_MISSING_AUTH_HEADER`).
2. **Authorization and ownership** — role membership in the endpoint's role list including the payment direction-role split (`ERR_ROLE_NOT_PERMITTED`); `Customer` ownership (`ERR_RESOURCE_NOT_FOUND`); segregation of duties on invoice void (`ERR_SOD_VIOLATION`).
3. **Existence** — left-to-right path resolution and body-referenced resources (`ERR_RESOURCE_NOT_FOUND`).
4. **Payload shape and basic constraints** — the request body, when present, must be a JSON object (an absent body is treated as empty, and unrecognized fields are ignored); required fields present; types and enum memberships valid; `qty` and `amount_cents` strictly positive; `effective_to` strictly later than `effective_from`; `scheduled_end` strictly later than `scheduled_start`; the deductible field matching the policy's `deductible_type`; photo parent and tag consistency (`ERR_INVALID_REQUEST`).
5. **Optimistic concurrency** — `expected_<parent>_version` matching the parent's current `version` (`ERR_STALE_VERSION`).
6. **State-machine legality** — the requested transition or action exists from the resource's current state, and child-creation state gates are satisfied (`ERR_INVALID_STATE_TRANSITION`, `ERR_CLAIM_NOT_PAYABLE`, `ERR_SUPPLEMENT_NOT_PERMITTED`, `ERR_ESTIMATE_NOT_EDITABLE`, `ERR_INVOICE_NOT_ISSUABLE`, `ERR_ROUND_NOT_OPEN`).
7. **Business safety gates** — the signed-authorization requirement (`ERR_AUTHORIZATION_MISSING`), mold containment (`ERR_CONTAINMENT_REQUIRED`), and the completion moisture gate (`ERR_MOISTURE_GATE_FAILED`).
8. **Business constraints** — evidence sufficiency, uniqueness, scheduling conflicts, and cross-references (`ERR_INSPECTION_INCOMPLETE`, `ERR_INSPECTION_EVIDENCE_INSUFFICIENT`, `ERR_SUPPLEMENT_EVIDENCE_INSUFFICIENT`, `ERR_DUPLICATE_INITIAL_ESTIMATE`, `ERR_DUPLICATE_ACTIVE_INVOICE`, `ERR_INSPECTION_SCHEDULE_CONFLICT`, `ERR_DISPOSITION_LINE_MISMATCH`, `ERR_CODE_UPGRADES_PENDING`, `ERR_PRICE_WINDOW_OVERLAP`).
9. **Temporal windows** — policy period, price list coverage, and authorization expiry (`ERR_POLICY_WINDOW_VIOLATION`, `ERR_PRICE_WINDOW_VIOLATION`, `ERR_AUTHORIZATION_EXPIRED`).
10. **Fiscal caps** — ordinance coverage and bucket caps (`ERR_ORDINANCE_NOT_COVERED`, `ERR_ORDINANCE_CAP_EXHAUSTED`), payment caps (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`, `ERR_DEDUCTIBLE_OVERPAID`).

The practical consequence: a request that is both unauthorized and malformed always reports the authorization failure; a stale-version write against a resource in an illegal state reports `ERR_STALE_VERSION`; on work completion, safety gates (priority 7) precede the code-upgrade closure check (priority 8), so a moisture-gate failure surfaces as `ERR_MOISTURE_GATE_FAILED` rather than being masked by a pending-upgrade failure; and temporal or fiscal failures surface only after every earlier tier has passed. Where several checks share a tier on one endpoint, the endpoint narratives in §3 state their evaluation order explicitly.

### 2.8. Money, Integer Cents, and Rounding

All monetary values are stored and transmitted as integer cents — prices, totals, deductibles, coverage limits, payment amounts. Rates and fractions (`tax_rate`, `overhead_rate`, `profit_rate`, `deductible_pct`, `ordinance_coverage_pct`, `depreciation_pct`, `default_depreciation_pct`) are decimal numbers applied against cent amounts.

Whenever a multiplication produces a fractional cent, the result is rounded half up to the nearest integer cent, and the rounding happens at the stage the calculation pins — never earlier, never later. Line-level money (`extended_cents`, `tax_cents`, `depreciation_cents`) rounds per line before any summation. Overhead and profit round at each of their two compounding stages. Moisture arithmetic is the one non-monetary computation: exceedances are expressed in reading points and drying-day classifications are whole days.

### 2.9. Optimistic Concurrency Control

Three write endpoints are guarded by optimistic concurrency control, and each requires its version field as a non-optional input:

- **Estimate creation** — `POST /v1/claims/{id}/estimates` requires `expected_claim_version` carrying the client's last observed `version` of the claim. Creating an estimate itself bumps the claim's `version` (supersede-style bookkeeping), so a client holding a stale claim version must re-read before creating. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Disposition append** — `POST /v1/negotiation-rounds/{id}/dispositions` requires `expected_negotiation_round_version` matching the round's current `version`. A round stays `OPEN` across appends, so only the version check orders the writes; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Line edit** — `PATCH /v1/estimates/{id}/lines/{line_id}` requires `expected_estimate_version` matching the estimate's current `version`. Draft and revised estimates accept unlimited sequential edits, so only the version check orders them; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. The OCC check sits at priority 5 (§2.7): it fires after authentication, authorization, existence, and payload validation, but before any state-machine or business rule is evaluated.

## 3. Business Logic & Workflows

### 3.1. Carrier Configuration and Carrier-Standard Price Lists

Before any claim can be estimated, a `ContractorAdmin` registers the carrier. A carrier record captures its display `name`, the sales `tax_rate` applied to taxable lines, and four negotiation-and-pricing parameters with house defaults: `overhead_rate` (default 0.10), `profit_rate` (default 0.10), `o_and_p_min_trades` (default 3 — the minimum number of distinct trades an estimate must span before overhead and profit apply), and `negotiation_response_days` (default 7 — how long a negotiation round stays open before deemed acceptance).

Each carrier owns a price list. A `ContractorAdmin` adds entries carrying a carrier-standard `category_code` (such as WTR-DEMO), a `trade` label (DEMOLITION, DRYWALL, PAINT, EQUIPMENT, CONTAINMENT, and similar — the distinct-trade count over an estimate drives the overhead-and-profit gate), a `kind` of `MATERIAL`, `LABOR`, or `EQUIPMENT`, a `unit` of measure (SF, DAY, EA), and a non-negative `unit_price_cents`. Two boolean flags steer downstream math: `tax_applicable` (default false) decides whether sales tax is charged on the line, and `o_and_p_eligible` (default false) decides whether the line's extended price joins the overhead-and-profit base. `default_depreciation_pct` (default 0) supplies the starting depreciation fraction for lines created from the entry.

Every entry is effective over a half-open window: `effective_from` is inclusive, `effective_to` is exclusive and must be strictly later than `effective_from` (an inverted window is rejected with `ERR_INVALID_REQUEST`). Within one carrier, windows for the same `category_code` may not overlap — a new entry whose window intersects an existing entry's window for that carrier and category code is rejected with `ERR_PRICE_WINDOW_OVERLAP` (HTTP 409) — but adjacency is allowed: an entry whose `effective_from` equals the prior entry's `effective_to` is a legal succession, not an overlap.

### 3.2. Policyholders, Policies, and Claim Intake

A `ContractorAdmin` onboards the insured as a customer with `full_name` and `email`, then writes the policy. A policy references its policyholder via `customer_id` and its issuer via `carrier_id`, carries a carrier-unique `policy_number`, a strictly positive `coverage_a_limit_cents` dwelling limit, and a policy period from `period_start` through `period_end` — a closed interval, inclusive at both ends. The deductible terms are governed by `deductible_type`: when it is `FLAT`, `flat_deductible_cents` is required; when it is `PERCENT_OF_COVERAGE_A`, `deductible_pct` is required instead. Supplying the wrong field for the declared type — or omitting the required one — is rejected with `ERR_INVALID_REQUEST`. The boolean `recoverable_depreciation` distinguishes an RCV policy (true, depreciation is recoverable) from an ACV-only policy (false).

Ordinance & law coverage is declared through `ordinance_coverage_pct` (a fraction of coverage A; default 0, meaning not covered) and `ordinance_flat_cap_cents` (a flat cap on the bucket; default 0). From these the policy's `ordinance_limit_cents` is computed once: the ordinance coverage percentage multiplied by `coverage_a_limit_cents`, rounded half up to integer cents, taken as the lesser value against the flat cap. With both terms at their defaults the limit is zero and no code upgrade can ever be approved against the policy (§3.7).

Opening a claim takes a `policy_id`, a `cause_of_loss` of `WATER`, `FIRE`, `WIND`, `MOLD`, or `HAIL`, a `date_of_loss`, and an optional `loss_address` (defaulting to an empty string). The `date_of_loss` must fall inside the policy period as a closed interval — on or after `period_start` and on or before `period_end` — or the creation is rejected with `ERR_POLICY_WINDOW_VIOLATION` (HTTP 422). At creation the system copies the policy's `customer_id` onto the claim for ownership checks and snapshots the deductible into `deductible_cents`: for a `FLAT` policy the snapshot is `flat_deductible_cents`; for a `PERCENT_OF_COVERAGE_A` policy it is the deductible percentage multiplied by `coverage_a_limit_cents`, rounded half up. The snapshot is taken once and never re-derived from payments. A new claim starts in `INTAKE` status with all money aggregates at zero and `payment_posture` `UNPAID`.

From intake, a `ContractorAdmin` steers the claim through the manual edges of its lifecycle using a transition capability that takes a target state `to` and an optional `reason`: `INTAKE → ASSESSING`, then `ASSESSING → ESTIMATING`. The same capability withdraws a pre-approval claim — `INTAKE`, `ASSESSING`, `ESTIMATING`, or `NEGOTIATING → WITHDRAWN`. An `Adjuster` uses it to deny a claim outright from `INTAKE`, `ASSESSING`, or `ESTIMATING` into `DENIED`. Any target state that is not a declared edge from the current state is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Every successful claim transition increments the claim's `version` by 1. The full claim lifecycle — `INTAKE`, `ASSESSING`, `ESTIMATING`, `NEGOTIATING`, `APPROVED`, `AUTHORIZED`, `IN_PROGRESS`, `ON_HOLD`, `COMPLETE`, `INVOICED`, `CLOSED`, `DENIED`, `WITHDRAWN` — is assembled across §3.5, §3.8, and §3.9; `CLOSED`, `DENIED`, and `WITHDRAWN` are terminal. A `Customer` listing claims sees only their own; staff roles may filter the claim list by `policy_id`, `customer_id`, or `status`.

### 3.3. Loss Assessment: Inspection Scheduling, Evidence, and Drying-Day Classification

While a claim is in `INTAKE` or `ASSESSING`, a `FieldTechnician` schedules inspections against it. An inspection is created with a `type` of `INITIAL` or `VERIFICATION`, an `assignee_id` identifying the field technician, and a half-open window from `scheduled_start` (inclusive) to `scheduled_end` (exclusive, strictly later than the start, enforced with `ERR_INVALID_REQUEST`). Creating an inspection against a claim in any other state violates the child-creation gate and is rejected with `ERR_INVALID_STATE_TRANSITION`. Scheduling also enforces a per-assignee travel buffer: for the same `assignee_id`, a new window conflicts with an existing scheduled window when the new start falls before the existing window's end plus 30 minutes and the new end falls after the existing window's start minus 30 minutes — the conflict is rejected with `ERR_INSPECTION_SCHEDULE_CONFLICT` (HTTP 409). A gap of exactly 30 minutes between windows is allowed.

An inspection begins `SCHEDULED`. While it is `SCHEDULED`, the technician records moisture readings against it — each with an `area` label, the `material` measured, the meter `reading_value`, the material's `dry_standard`, and the `recorded_at` timestamp. The system derives `is_wet` on each reading: a reading is wet when its `reading_value` is strictly greater than its `dry_standard` plus a margin of 2. Photos attach to the claim with a `claim_id` plus exactly one of `inspection_id` or `supplement_id` — never both, never neither — and a `tag` of `LOSS_OVERVIEW`, `AREA`, `MOISTURE_PROOF`, `SUPPLEMENT_EVIDENCE`, or `COMPLETION`, along with an opaque `file_ref` and the `captured_at` timestamp. Tag consistency with the parent is enforced: a photo attached via `supplement_id` must carry `SUPPLEMENT_EVIDENCE`. Violations of the parent exclusivity or tag consistency are rejected with `ERR_INVALID_REQUEST`.

Completing an inspection is gated on evidence, evaluated only after the inspection is confirmed `SCHEDULED`. At least 3 photos attached to this inspection with a tag of `LOSS_OVERVIEW`, `AREA`, or `MOISTURE_PROOF` must exist, and when the claim's `cause_of_loss` is `WATER` or `MOLD`, at least one moisture reading must exist on the inspection; failing either requirement rejects the completion with `ERR_INSPECTION_EVIDENCE_INSUFFICIENT` (HTTP 422). On completion the system stamps `completed_at` from the logical clock and computes two sanctioned drying-day classifications from the inspection's readings. For every reading, the exceedance is its `reading_value` minus its `dry_standard`. The **worst variant**, stored as `drying_days_worst_variant`, takes the single largest exceedance over all readings (zero when there are none): an exceedance of 8 or less classifies 1 drying day, greater than 8 and at most 20 classifies 3, and greater than 20 classifies 5. The **mean variant**, stored as `drying_days_mean_variant`, averages the exceedances over only the wet readings (zero when none are wet): a mean of 8 or less classifies 1 day, greater than 8 and at most 20 classifies 2, and greater than 20 classifies 4. The two variants are stored side by side — the carrier-mandated classification reads the worst single point; the contractor's provisional classification reads the area-weighted mean and typically yields fewer equipment days. Both remain null until the inspection completes. A `SCHEDULED` inspection may instead be canceled, moving it to `CANCELED` with no further effects.

### 3.4. Estimate Composition and Line-Item Pricing

An `Estimator` opens the pricing phase by creating an estimate against a claim — always of `type` `INITIAL`, the only kind created manually; `SUPPLEMENT` estimates are system-spawned later (§3.6). Creation requires the claim to be in `ASSESSING`, `ESTIMATING`, or `NEGOTIATING` (otherwise `ERR_INVALID_STATE_TRANSITION`), is guarded by the claim-version OCC rule of §2.9 via `expected_claim_version`, and is capped at one `INITIAL` estimate per claim — a second attempt is rejected with `ERR_DUPLICATE_INITIAL_ESTIMATE` (HTTP 409). Creating the estimate increments the claim's `version` by 1, which is exactly why the OCC guard exists. Each estimate receives a per-claim `revision_number`: one greater than the highest `revision_number` among the claim's existing estimates. A new estimate starts in `DRAFT`.

Lines are added to a `DRAFT` (or `REVISED`) estimate one at a time by reference to a `price_list_entry_id`, with a strictly positive planned `qty` and optional `depreciation_pct`, `depreciation_recoverable` (default true), and `description` (default empty). At add time the line pins `unit_price_cents` from the entry and copies the entry's `category_code`, `trade`, `kind`, `tax_applicable`, and `o_and_p_eligible`; when `depreciation_pct` is omitted it defaults to the entry's `default_depreciation_pct`. Every line mutation — add, edit, or removal — recomputes the estimate's totals and increments the estimate's `version` by 1. While the estimate is `DRAFT` or `REVISED` an `Estimator` may also edit a line's `qty` or pinned `unit_price_cents` (the OCC-guarded edit of §2.9, taking `expected_estimate_version`), or remove a line entirely, which sets its `negotiation_status` to `REMOVED` and excludes it from every total. Any line mutation against an estimate that is not in an editable state — and any recording of actuals outside its window (§3.8) — is rejected with `ERR_ESTIMATE_NOT_EDITABLE` (HTTP 409).

Estimate money is built in pinned stages. Each line's `extended_cents` is its `qty` multiplied by its `unit_price_cents`, rounded half up to integer cents **per line first**; the estimate's `rcv_total_cents` is then the sum of `extended_cents` over all lines whose `negotiation_status` is not `REMOVED`. The order is load-bearing: three lines of quantity 0.335 at 199 cents each total 201 cents when each line is rounded before summation, whereas summing first and rounding once would yield 200 — the per-line-then-sum order is the specified behavior. Sales tax rides on the extended price before overhead and profit: each non-removed line with `tax_applicable` true contributes a `tax_cents` of its `extended_cents` multiplied by the carrier's `tax_rate`, rounded half up per line, and the estimate's `tax_total_cents` is their sum.

Overhead and profit are gated and compounded. Count the distinct `trade` values over the estimate's non-removed lines; if that count is at least the carrier's `o_and_p_min_trades`, take the base as the sum of `extended_cents` over the non-removed lines with `o_and_p_eligible` true, compute the overhead as that base multiplied by the carrier's `overhead_rate` rounded half up, then compute the profit as the base plus overhead, multiplied by the carrier's `profit_rate`, again rounded half up — a sequential compounding, so profit is levied on the overhead-inclusive amount. The estimate's `overhead_profit_total_cents` is overhead plus profit; when the trade gate is not met it is exactly 0. Overhead and profit themselves are never taxed.

Depreciation applies to line extended amounts only — never to tax or overhead and profit. Each non-removed line's `depreciation_cents` is its `extended_cents` multiplied by its `depreciation_pct`, rounded half up. The estimate's `depreciation_total_cents` sums these, while `recoverable_depreciation_cents` sums only the portions from lines whose `depreciation_recoverable` is true, and only when the claim's policy has `recoverable_depreciation` true — an ACV-only policy recovers nothing. Finally, `grand_total_cents` is `rcv_total_cents` plus `tax_total_cents` plus `overhead_profit_total_cents`, and `acv_total_cents` is `grand_total_cents` minus `depreciation_total_cents`.

All of the above run in a **provisional** variant during the estimate lifecycle — planned `qty` drives every figure. A **final** variant, driven by recorded `qty_actual`, exists solely for invoice creation and is specified in §3.9. At the claim level, `rcv_total_cents`, `acv_total_cents`, and `recoverable_depreciation_cents` are recomputed whenever the approved estimate set changes: each is the sum of the same-named estimate figure over the claim's estimates in `APPROVED` or `LOCKED` status. Estimates in `DRAFT`, `SUBMITTED`, `COUNTERED`, `REVISED`, or `DENIED` contribute nothing to claim aggregates.

### 3.5. Estimate Submission, Adjuster Negotiation, and Deemed Acceptance

Submission by an `Estimator` moves an estimate from `DRAFT` — or from `REVISED` on a resubmission — to `SUBMITTED`, and enforces its checks in priority order (§2.7). The estimate must hold at least one line whose `negotiation_status` is not `REMOVED` (`ERR_INVALID_REQUEST`, priority 4). The state gate follows (priority 6): an `INITIAL` estimate submits only while the claim is in `ESTIMATING` or `NEGOTIATING`, and a `SUPPLEMENT` estimate only while the claim is `IN_PROGRESS`; violation is `ERR_INVALID_STATE_TRANSITION`. Next, the claim must carry at least one inspection in `COMPLETED` status (`ERR_INSPECTION_INCOMPLETE`, HTTP 422, priority 8). Last, the temporal gate (priority 9): every non-removed line's price list entry must cover the claim's `date_of_loss` within its half-open window — `effective_from` on or before the loss date and the loss date strictly before `effective_to` — else `ERR_PRICE_WINDOW_VIOLATION` (HTTP 422). A successful submission stamps `submitted_at` from the logical clock, increments the estimate's `version`, and — when resubmitting from `REVISED` — reverts every line whose `negotiation_status` was `DISPUTED` back to `PENDING`. Submission cascades to the claim only for `INITIAL` estimates: while the claim is `ESTIMATING`, the claim moves `ESTIMATING → NEGOTIATING` with its `version` incremented. A `SUPPLEMENT` submission leaves an `IN_PROGRESS` claim untouched.

An `Adjuster` may then approve the `SUBMITTED` estimate outright, deny it, or counter it. Approval moves the estimate to `APPROVED`, flips every non-removed line's `negotiation_status` to `AGREED`, stamps `approved_at`, increments the estimate's `version`, recomputes the claim aggregates (§3.4), and — for an `INITIAL` estimate while the claim is `NEGOTIATING` — moves the claim `NEGOTIATING → APPROVED` with claim aggregates recomputed and the claim's `version` incremented. Denial moves the estimate `SUBMITTED → DENIED`; for an `INITIAL` estimate under a `NEGOTIATING` claim, the claim moves to `DENIED` as well, while denying a `SUPPLEMENT` estimate never moves the claim.

A counter-offer creates a negotiation round: the `Adjuster` posts a set of `dispositions`, each naming an `estimate_line_id` together with any of `proposed_qty`, `proposed_unit_price_cents`, or a `propose_removal` flag (default false). Every targeted line must belong to this estimate, else the whole counter-offer is rejected with `ERR_DISPOSITION_LINE_MISMATCH` (HTTP 422). The round is created `OPEN`, recording the countered estimate in its `estimate_id`, with a per-estimate `round_number` — one greater than the highest round number on the estimate — and a `due_at` of its creation time plus the carrier's `negotiation_response_days` days. Each disposition in turn records its owning round in `negotiation_round_id`. The estimate moves `SUBMITTED → COUNTERED` with its `version` incremented, and each targeted line still `PENDING` has its `negotiation_status` flipped to `DISPUTED` (a targeted line already `REMOVED` keeps its status). The round's `disputed_amount_cents` is recomputed as dispositions are added or answered: for each `PENDING` disposition, multiply the proposed quantity by the proposed unit price — each falling back to the line's current value when that proposal is null — round the product half up to integer cents, take the absolute difference against the line's current `extended_cents`, and sum those differences. While the round is `OPEN` the `Adjuster` may append further dispositions through the OCC-guarded append of §2.9, which takes `expected_negotiation_round_version`, requires the round `OPEN` (`ERR_ROUND_NOT_OPEN`, HTTP 409), marks the new dispositions `PENDING` and flips each targeted line still `PENDING` to `DISPUTED`, recomputes `disputed_amount_cents`, and increments the round's `version`.

The `Estimator` answers each disposition with an `outcome` of `ACCEPT` or `REJECT`. Two state checks guard the answer, and within priority 6 they run in a fixed order: the disposition's own status is checked first — answering a non-`PENDING` disposition is `ERR_INVALID_STATE_TRANSITION` — and only then the round's status, a non-`OPEN` round yielding `ERR_ROUND_NOT_OPEN`. An `ACCEPT` applies the proposal to the line: `qty` becomes `proposed_qty` when set, `unit_price_cents` becomes `proposed_unit_price_cents` when set, and the line moves to `REMOVED` when `propose_removal` is set, otherwise to `AGREED`; estimate totals are then recomputed. When an answer leaves no `PENDING` dispositions, the round auto-resolves to `RESOLVED`, and if every disposition was `ACCEPTED` the estimate auto-approves with exactly the application, totals, and claim-side effects of an approval or concession. A `REJECT` moves the disposition to `REJECTED`, leaves the line `DISPUTED` and the estimate `COUNTERED`, awaiting revision or concession; the round still auto-resolves when nothing remains `PENDING`.

Instead of answering line by line, the `Estimator` holding a `COUNTERED` estimate with an `OPEN` round may concede: every `PENDING` disposition is applied at its proposed values under the same rules as `ACCEPT`, the round moves to `RESOLVED`, totals are recomputed, and the estimate moves `COUNTERED → APPROVED` with the same claim-side effects as an approval. Alternatively the `Estimator` may revise the `COUNTERED` estimate, moving it to `REVISED` and reverting all `DISPUTED` lines to `PENDING` for re-editing under §3.4. Finally, the deemed-acceptance sweep: when the logical clock is advanced past an `OPEN` round's `due_at` (§2.4), the round expires to `EXPIRED`, every `PENDING` disposition is auto-accepted at its proposed values, and the estimate auto-approves with the full claim-side effects — the carrier's silence is treated as acceptance.

### 3.6. Supplements for Discovered Damage and the Scope-Drift Cascade

Damage discovered mid-repair enters through a supplement. An `Estimator` creates one against a claim carrying a `narrative` of the discovery; creation is permitted only while the claim is `IN_PROGRESS`, and is otherwise rejected with `ERR_SUPPLEMENT_NOT_PERMITTED` (HTTP 409). The supplement starts `DRAFT`. Submitting it requires a non-empty `narrative` and at least 2 photos attached to this supplement with the `SUPPLEMENT_EVIDENCE` tag; failure is `ERR_SUPPLEMENT_EVIDENCE_INSUFFICIENT` (HTTP 422). Submission moves the supplement `DRAFT → SUBMITTED` and stamps `submitted_at`.

An `Adjuster` then decides the supplement. Denial moves it `SUBMITTED → DENIED`; approval moves it `SUBMITTED → APPROVED`, stamps `decided_at` (as does denial), increments the claim's `version` by 1, and — the key side effect — spawns a new estimate with `type` `SUPPLEMENT`, the supplement's id recorded in `supplement_id`, status `DRAFT`, and the next per-claim `revision_number`. That estimate is composed, submitted, and negotiated exactly like any other (§3.4, §3.5), except that its submission requires the claim `IN_PROGRESS` and never moves the claim.

Approving a `SUPPLEMENT` estimate fires the scope-drift cascade, in order: the estimate moves to `APPROVED`; the claim's `rcv_total_cents` is recomputed over the now-larger approved set; and the new total is compared against the `scope_rcv_cents` snapshot on the claim's `SIGNED` work authorization. When the absolute drift is strictly greater than 10 percent of `scope_rcv_cents` — with the 10 percent threshold itself rounded half up to integer cents, and a drift of exactly 10 percent *not* voiding — the authorization is auto-voided with `voided_reason` `SCOPE_DRIFT`, and a claim in `IN_PROGRESS` drops to `ON_HOLD` with its `version` incremented. A drift within tolerance has no side effects. The claim then waits `ON_HOLD` until a fresh authorization is signed (§3.8).

### 3.7. Ordinance & Law Code Upgrades

Code-driven scope — a citation such as NEC 2023 AFCI — is tracked as a code upgrade. An `Estimator` identifies one against any claim not in a terminal state (`CLOSED`, `DENIED`, `WITHDRAWN`), supplying the `code_citation`, a `description` of the required scope, and a strictly positive `estimated_cost_cents`; the item starts `IDENTIFIED`. An `Adjuster` may deny an `IDENTIFIED` item outright, or approve it — optionally overriding the contractor's figure with an `approved_cost_cents`, which defaults to `estimated_cost_cents` when omitted and, when supplied, must be strictly positive. Approval additionally requires the claim to be non-terminal; approving against a terminal claim is rejected with `ERR_INVALID_STATE_TRANSITION` (denial carries no such claim-state check).

Approval allocates from the policy's ordinance bucket, and its fiscal checks run in a fixed order at priority 10: a policy whose `ordinance_limit_cents` is zero rejects the approval with `ERR_ORDINANCE_NOT_COVERED` (HTTP 422); a covered policy whose bucket remaining is zero rejects with `ERR_ORDINANCE_CAP_EXHAUSTED` (HTTP 422). The bucket remaining is the policy's `ordinance_limit_cents` minus the sum of `covered_cents` over the claim's code upgrades currently in `APPROVED`. Allocation is incremental at approval time, ordered by `approved_at` ascending with ties broken by `created_at` ascending: the approving item's `covered_cents` is the lesser of its `approved_cost_cents` and the bucket remaining — so when the remaining amount is at least the approved cost the item is covered in full, and at the exhaustion boundary coverage is partial. The uninsured remainder becomes `customer_responsibility_cents`, the approved cost minus the covered amount, and the claim's `ordinance_consumed_cents` is recomputed as the sum of `covered_cents` over `APPROVED` items. Approval stamps `approved_at` from the logical clock.

Withdrawal is the compensation path: an `Estimator` may withdraw an `APPROVED` item, moving it to `WITHDRAWN`, releasing its `covered_cents` back to the bucket and recomputing `ordinance_consumed_cents`. Items identified but never decided also block job completion, as §3.8 describes.

### 3.8. Work Authorization, Job Execution, and Completion Gates

Once a claim is `APPROVED` — or later, when it sits `ON_HOLD` after a scope-drift void — a `ContractorAdmin` prepares a work authorization carrying two customer-facing declarations: `direct_pay_assignment`, the assignment of benefits under which the carrier pays the contractor directly, and `deductible_acknowledged`, the customer's acknowledgment of the deductible obligation (anti-waiver compliance). Creation outside `APPROVED` or `ON_HOLD` is rejected with `ERR_INVALID_STATE_TRANSITION`.

Signing belongs to the `Customer` alone: the caller's `X-User-ID` must equal the claim's `customer_id` (otherwise `ERR_RESOURCE_NOT_FOUND`, per §2.1), and the authorization must still be `DRAFT`. Signing snapshots `scope_rcv_cents` from the claim's current `rcv_total_cents` — the drift baseline for §3.6 — stamps `signed_at` from the logical clock, and sets `expires_at` exactly 30 days later. Signing then moves the claim: from `APPROVED` to `AUTHORIZED`, or from `ON_HOLD` back to `IN_PROGRESS`. When a signing under an `APPROVED` claim has `direct_pay_assignment` true, the system auto-creates the first carrier payment: a `Payment` of `type` `ACV_ADVANCE`, direction `CARRIER_TO_CONTRACTOR`, status `REQUESTED`, `auto_created` true, in the amount of the claim's `acv_total_cents` minus its `deductible_cents`, floored at zero — the deductible is netted out of the first carrier payment and is never paid by the carrier. When that difference is not positive, no payment is created. Without direct pay, no payment is auto-created; the carrier pays the customer out of band and the customer settles with the contractor at invoice time.

Starting work moves the claim from `APPROVED` or `AUTHORIZED` to `IN_PROGRESS` and is gated by three tiers in priority order. The state gate first (priority 6): any other claim status is `ERR_INVALID_STATE_TRANSITION`. The safety gates next (priority 7): a work authorization in `SIGNED` status with `deductible_acknowledged` true must exist for the claim — otherwise `ERR_AUTHORIZATION_MISSING` (HTTP 409) — and, when the claim's `cause_of_loss` is `MOLD`, an `APPROVED` or `LOCKED` estimate of the claim must contain a non-removed line whose `trade` is CONTAINMENT, else `ERR_CONTAINMENT_REQUIRED` (HTTP 422). The temporal gate last (priority 9): the logical clock must not have passed the authorization's `expires_at`, else `ERR_AUTHORIZATION_EXPIRED` (HTTP 422). In practice the authorization check makes the `APPROVED` edge unreachable — signing auto-advances the claim to `AUTHORIZED` — but both edges are enforced as defense in depth. A successful start increments the claim's `version`.

While the claim is `IN_PROGRESS` (or `COMPLETE`), the `Estimator` records actual quantities against each `APPROVED` estimate through a record-actuals capability taking `entries`, each pairing an `estimate_line_id` with its completed `qty_actual`. Each `qty_actual` must be zero or positive; an `estimate_line_id` that does not resolve is `ERR_RESOURCE_NOT_FOUND`, and one resolving to a line of another estimate is `ERR_INVALID_REQUEST`. Until recorded, `qty_actual` is null. Recording actuals increments the estimate's `version` but deliberately does **not** recompute the estimate's provisional totals — the provisional basis agreed at approval is preserved; actuals take effect only in the final-variant invoice of §3.9, where a `qty_actual` of zero excludes the line entirely. Once an estimate is `LOCKED`, record-actuals is refused with `ERR_ESTIMATE_NOT_EDITABLE`.

Completing the work moves `IN_PROGRESS → COMPLETE` behind two gates, evaluated in priority order: the safety moisture gate first (priority 7), then the code-upgrade closure check (priority 8). For a claim whose `cause_of_loss` is `WATER` or `MOLD`, the moisture gate groups all readings across the claim's inspections by (`area`, `material`); for every group containing at least one reading with `is_wet` true, the latest reading — by `recorded_at`, ties broken by `created_at` — must be at most the group's `dry_standard` plus 2, else completion is rejected with `ERR_MOISTURE_GATE_FAILED` (HTTP 422). Independently, if any code upgrade on the claim is still `IDENTIFIED`, completion is rejected with `ERR_CODE_UPGRADES_PENDING` (HTTP 409). Both gates passing moves the claim to `COMPLETE` and increments its `version`.

### 3.9. Invoicing, Depreciation Recovery, and the Payment Ledger

With the claim `COMPLETE`, a `ContractorAdmin` creates the invoice. Creation requires the claim `COMPLETE` (priority 6) and at most one non-`VOIDED` invoice per claim — a second active invoice is `ERR_DUPLICATE_ACTIVE_INVOICE` (HTTP 409, priority 8). The invoice's `total_cents` is the **final-variant** grand total: every approved estimate is recomputed with `qty_actual` overriding the planned quantity wherever recorded (a recorded zero excludes the line), removed lines excluded, per-line rounding, tax, the trade gate re-evaluated on the final line set, overhead-and-profit compounding, and the depreciation split all reapplied exactly as §3.4 specifies — so the two variants diverge whenever actuals differ from plan. Creation also locks the estimate set: every `APPROVED` estimate of the claim moves to `LOCKED`, freezing it against further record-actuals. The invoice records its creator's `X-User-ID` in `created_by_user_id` and starts `DRAFT`, with `applied_cents` initialized to the claim's already-`CLEARED` payment total capped at `total_cents` and `outstanding_cents` set to the difference.

Issuing the invoice moves it `DRAFT → ISSUED`, but only while the claim is `COMPLETE`; any other combination is `ERR_INVOICE_NOT_ISSUABLE` (HTTP 409). Issuance stamps `issued_at`, moves the claim `COMPLETE → INVOICED` with its `version` incremented, and copies the invoice's `outstanding_cents` into the claim's `outstanding_balance_cents`. It also runs the depreciation-recovery waterfall in a pinned order: start from the claim's `deductible_cents` (the policy snapshot, never derived from payments); take `acv_advance_paid` as the sum of `CLEARED` `ACV_ADVANCE` payments; compute the actual spend gap as the invoice's `total_cents` minus `acv_advance_paid` minus `deductible_cents`, floored at zero; the recovery is the lesser of the claim's `recoverable_depreciation_cents` and that gap — never exceeding the depreciation withheld, and never exceeding what the customer actually spent beyond advance plus deductible, so a smaller final invoice reduces the recovery cent-for-cent. When the recovery is positive, the system auto-creates a `Payment` of `type` `DEPRECIATION_RECOVERY`, direction `CARRIER_TO_CONTRACTOR`, status `REQUESTED`, `auto_created` true, with `invoice_id` set to this invoice. An issued-but-unsettled invoice sets the claim's `payment_posture` to `DEPRECIATION_PENDING`.

Payments move money in both directions. Manual payments are recorded against a claim with a `type` and a strictly positive `amount_cents`: a `Customer` records `DEDUCTIBLE` payments against their own claim; a `ContractorAdmin` records `CUSTOMER_BALANCE` payments. (The carrier-direction types `ACV_ADVANCE` and `DEPRECIATION_RECOVERY` are only ever system-created, with `auto_created` true; recording one manually is rejected with `ERR_INVALID_REQUEST`.) The claim must be in a payable state — `AUTHORIZED`, `IN_PROGRESS`, `ON_HOLD`, `COMPLETE`, or `INVOICED` — else `ERR_CLAIM_NOT_PAYABLE` (HTTP 409). Fiscal caps apply at priority 10: a `CUSTOMER_BALANCE` payment may not exceed the active invoice's `outstanding_cents` once that invoice is `ISSUED` or `SETTLED` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`, HTTP 422) — while the only active invoice is still `DRAFT`, no cap is applied — and a `DEDUCTIBLE` payment may not push the running total of deductible payments in `CLEARED`, `ISSUED`, `APPROVED`, or `REQUESTED` status plus the new amount above the claim's `deductible_cents` — exactly equal is allowed — else `ERR_DEDUCTIBLE_OVERPAID` (HTTP 422). Every payment's `direction` is derived from its type: `ACV_ADVANCE` and `DEPRECIATION_RECOVERY` run `CARRIER_TO_CONTRACTOR`; `DEDUCTIBLE` and `CUSTOMER_BALANCE` run `CUSTOMER_TO_CONTRACTOR`.

A payment walks the lifecycle `REQUESTED → APPROVED → ISSUED → CLEARED`, with a return path and a requeue. Approval and issuance enforce the direction-role split at priority 2: a `CARRIER_TO_CONTRACTOR` payment requires the `Adjuster`, a `CUSTOMER_TO_CONTRACTOR` payment requires the `ContractorAdmin`, and a mismatch is `ERR_ROLE_NOT_PERMITTED`. Approving a carrier-direction payment additionally requires a signed, deductible-acknowledged work authorization on the claim, else `ERR_AUTHORIZATION_MISSING`. Clearing is a `ContractorAdmin` action that moves `ISSUED → CLEARED` and reconciles the ledger: the claim's `carrier_paid_cents` (sum of `CLEARED` carrier-direction payments — the `ACV_ADVANCE` and `DEPRECIATION_RECOVERY` types), `customer_paid_cents` (sum of `CLEARED` customer-direction payments — `DEDUCTIBLE` and `CUSTOMER_BALANCE`), and `deductible_collected_cents` (the `CLEARED` `DEDUCTIBLE` subset) are recomputed, and the active invoice's `applied_cents` is recomputed as the sum of the claim's `CLEARED` payment amounts capped at its `total_cents`, with `outstanding_cents` the difference. When a clearing makes `applied_cents` reach `total_cents`, the invoice settles to `SETTLED`, the claim moves `INVOICED → CLOSED`, and its `payment_posture` becomes `PAID_IN_FULL`. A bounced or clawed-back payment moves `ISSUED → RETURNED` or `CLEARED → RETURNED`: a payment that had been cleared is excluded as the paid counters, invoice `applied_cents`, and posture are recomputed. A `RETURNED` payment may be re-presented, moving back to `REQUESTED`.

The claim's `payment_posture` summarizes the ledger at every moment: `PAID_IN_FULL` when the active invoice is `SETTLED`; `DEPRECIATION_PENDING` while an active invoice is `ISSUED` but unsettled; `ADVANCE_PAID` when no invoice has been issued and `carrier_paid_cents` is positive; otherwise `UNPAID`. The claim's `outstanding_balance_cents` is zero until an invoice is issued, and thereafter mirrors the active invoice's `outstanding_cents`. The conserved quantity throughout: an invoice's `total_cents` always equals its `outstanding_cents` plus the cleared payments applied to it. A computed financial summary per claim exposes `rcv_total_cents`, `acv_total_cents`, `grand_total_cents`, `depreciation_total_cents`, `recoverable_depreciation_cents`, `deductible_cents`, `deductible_collected_cents`, `carrier_paid_cents`, `customer_paid_cents`, `outstanding_balance_cents`, `ordinance_limit_cents`, `ordinance_consumed_cents`, and `payment_posture` in one read.

Voiding an invoice is the compensation path and carries a segregation-of-duties rule at priority 2: the caller's `X-User-ID` must differ from the invoice's `created_by_user_id`, else `ERR_SOD_VIOLATION` (HTTP 403). Voiding a `DRAFT` invoice simply moves it to `VOIDED` and increments the claim's `version`. Voiding an `ISSUED` invoice compensates fully: any auto-created `DEPRECIATION_RECOVERY` payment still in `REQUESTED` is moved to `VOIDED` (a system transition that applies only to auto-created payments), the claim returns `INVOICED → COMPLETE` with its `version` incremented, its `outstanding_balance_cents` reset to zero, and `payment_posture` recomputed — leaving the claim ready for a corrected invoice to be created.

## 4. Endpoint Definitions

Endpoints that create a new resource (or add a new resource to a collection) return `201 Created`; endpoints that modify, transition, or act on an existing resource return `200 OK`. Successful create and modify operations return the affected resource in the envelope's `data` field (§2.2). The table below summarizes the HTTP contract only; request parameters, preconditions, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Advance the logical clock; fires the negotiation-round expiry sweep | ContractorAdmin |
| POST | `/v1/carriers` | Create a carrier pricing/tax configuration | ContractorAdmin |
| GET | `/v1/carriers/{id}` | Read a carrier | ContractorAdmin, Estimator, Adjuster |
| POST | `/v1/carriers/{id}/price-list-entries` | Add a price list entry with a half-open effective window; overlap rejected | ContractorAdmin |
| GET | `/v1/carriers/{id}/price-list-entries` | List a carrier's price entries | ContractorAdmin, Estimator, Adjuster |
| POST | `/v1/customers` | Create an insured customer | ContractorAdmin |
| POST | `/v1/policies` | Create a policy with coverage, deductible, and ordinance terms | ContractorAdmin |
| GET | `/v1/policies/{id}` | Read a policy | ContractorAdmin, Estimator, Adjuster |
| GET | `/v1/policies` | List policies | ContractorAdmin, Estimator, Adjuster |
| POST | `/v1/claims` | Open a claim; deductible snapshotted; loss date must sit inside the policy period | ContractorAdmin |
| GET | `/v1/claims` | List claims; Customer sees only their own | ContractorAdmin, Estimator, Adjuster, Customer |
| GET | `/v1/claims/{id}` | Read a claim including computed aggregates | ContractorAdmin, Estimator, Adjuster, Customer |
| POST | `/v1/claims/{id}/transition` | Manual claim transitions (intake/assessing/estimating, withdraw, adjuster deny) | ContractorAdmin, Adjuster |
| POST | `/v1/claims/{id}/start-work` | Start work with authorization, containment, and expiry gates | ContractorAdmin |
| POST | `/v1/claims/{id}/complete-work` | Complete work behind the moisture and code-upgrade gates | ContractorAdmin |
| GET | `/v1/claims/{id}/financial-summary` | Computed read of all claim money fields and the ordinance bucket | ContractorAdmin, Estimator, Adjuster, Customer |
| POST | `/v1/claims/{id}/inspections` | Schedule an inspection; per-assignee buffered overlap rejected | FieldTechnician |
| GET | `/v1/claims/{id}/inspections` | List a claim's inspections | ContractorAdmin, Estimator, FieldTechnician, Adjuster |
| GET | `/v1/inspections/{id}` | Read an inspection including drying-day variants | ContractorAdmin, Estimator, FieldTechnician, Adjuster |
| POST | `/v1/inspections/{id}/complete` | Complete an inspection after the evidence gates | FieldTechnician |
| POST | `/v1/inspections/{id}/cancel` | Cancel a scheduled inspection | FieldTechnician |
| POST | `/v1/inspections/{id}/readings` | Add a moisture reading while the inspection is scheduled | FieldTechnician |
| GET | `/v1/inspections/{id}/readings` | List an inspection's readings | ContractorAdmin, Estimator, FieldTechnician, Adjuster |
| POST | `/v1/photos` | Attach a photo to a claim via exactly one parent; tag consistency enforced | FieldTechnician, Estimator |
| GET | `/v1/photos/{id}` | Read a photo record | ContractorAdmin, Estimator, FieldTechnician, Adjuster |
| GET | `/v1/photos` | List photos filtered by any foreign key or tag | ContractorAdmin, Estimator, FieldTechnician, Adjuster |
| POST | `/v1/claims/{id}/estimates` | Create the claim's INITIAL estimate (OCC-guarded on claim version) | Estimator |
| GET | `/v1/claims/{id}/estimates` | List a claim's estimates | ContractorAdmin, Estimator, Adjuster, Customer |
| GET | `/v1/estimates/{id}` | Read an estimate including computed totals | ContractorAdmin, Estimator, Adjuster, Customer |
| POST | `/v1/estimates/{id}/lines` | Add a line pinned to a price list entry | Estimator |
| GET | `/v1/estimates/{id}/lines` | List an estimate's lines | ContractorAdmin, Estimator, Adjuster, Customer |
| PATCH | `/v1/estimates/{id}/lines/{line_id}` | Edit a line's quantity or price while editable (OCC-guarded on estimate version) | Estimator |
| POST | `/v1/estimates/{id}/lines/{line_id}/remove` | Mark a line removed while the estimate is editable | Estimator |
| POST | `/v1/estimates/{id}/submit` | Submit an estimate; INITIAL submission moves the claim to negotiating | Estimator |
| POST | `/v1/estimates/{id}/revise` | Revise a countered estimate; disputed lines revert to pending | Estimator |
| POST | `/v1/estimates/{id}/concede` | Concede a countered estimate, applying every pending disposition | Estimator |
| POST | `/v1/estimates/{id}/approve` | Approve a submitted estimate; supplement approval fires the scope-drift cascade | Adjuster |
| POST | `/v1/estimates/{id}/deny` | Deny a submitted estimate; INITIAL denial moves the claim to denied | Adjuster |
| POST | `/v1/estimates/{id}/record-actuals` | Record completed quantities per line against an approved estimate | Estimator |
| POST | `/v1/estimates/{id}/negotiation-rounds` | Adjuster counter-offer: open a round with initial dispositions | Adjuster |
| GET | `/v1/estimates/{id}/negotiation-rounds` | List an estimate's negotiation rounds | ContractorAdmin, Estimator, Adjuster |
| GET | `/v1/negotiation-rounds/{id}` | Read a round including its disputed amount | ContractorAdmin, Estimator, Adjuster |
| POST | `/v1/negotiation-rounds/{id}/dispositions` | Append dispositions to an open round (OCC-guarded on round version) | Adjuster |
| GET | `/v1/negotiation-rounds/{id}/dispositions` | List a round's dispositions | ContractorAdmin, Estimator, Adjuster |
| POST | `/v1/dispositions/{id}/respond` | Answer a disposition: accept applies the proposal, reject keeps it disputed | Estimator |
| POST | `/v1/claims/{id}/supplements` | Open a supplement for discovered damage; requires work in progress | Estimator |
| GET | `/v1/claims/{id}/supplements` | List a claim's supplements | ContractorAdmin, Estimator, Adjuster |
| GET | `/v1/supplements/{id}` | Read a supplement | ContractorAdmin, Estimator, Adjuster |
| POST | `/v1/supplements/{id}/submit` | Submit a supplement after the evidence gate | Estimator |
| POST | `/v1/supplements/{id}/approve` | Approve a supplement; spawns a SUPPLEMENT estimate | Adjuster |
| POST | `/v1/supplements/{id}/deny` | Deny a submitted supplement | Adjuster |
| GET | `/v1/supplements/{id}/estimates` | List estimates spawned by a supplement | ContractorAdmin, Estimator, Adjuster |
| POST | `/v1/claims/{id}/code-upgrades` | Identify an ordinance & law code upgrade item | Estimator |
| GET | `/v1/claims/{id}/code-upgrades` | List a claim's code upgrades | ContractorAdmin, Estimator, Adjuster |
| POST | `/v1/code-upgrades/{id}/approve` | Approve a code upgrade with waterfall allocation into the ordinance bucket | Adjuster |
| POST | `/v1/code-upgrades/{id}/deny` | Deny a code upgrade | Adjuster |
| POST | `/v1/code-upgrades/{id}/withdraw` | Withdraw an approved code upgrade; releases its covered amount | Estimator |
| POST | `/v1/claims/{id}/work-authorizations` | Create a work authorization (direct-pay assignment, deductible acknowledgment) | ContractorAdmin |
| GET | `/v1/claims/{id}/work-authorizations` | List a claim's work authorizations | ContractorAdmin, Estimator, Customer |
| POST | `/v1/work-authorizations/{id}/sign` | Customer signs; snapshots scope, sets 30-day expiry, may auto-create the ACV advance | Customer |
| POST | `/v1/claims/{id}/invoices` | Create the final invoice from final-variant totals; locks the approved estimates | ContractorAdmin |
| GET | `/v1/claims/{id}/invoices` | List a claim's invoices | ContractorAdmin, Adjuster, Customer |
| GET | `/v1/invoices/{id}` | Read an invoice | ContractorAdmin, Adjuster, Customer |
| POST | `/v1/invoices/{id}/issue` | Issue the invoice; moves the claim to invoiced; may auto-create the recovery payment | ContractorAdmin |
| POST | `/v1/invoices/{id}/void` | Void a draft or issued invoice (segregation of duties); issued void compensates | ContractorAdmin |
| GET | `/v1/invoices/{id}/payments` | List payments tied to an invoice | ContractorAdmin, Adjuster, Customer |
| POST | `/v1/claims/{id}/payments` | Record a manual deductible or customer-balance payment; fiscal caps enforced | ContractorAdmin, Customer |
| GET | `/v1/claims/{id}/payments` | List a claim's payments, ordered by creation ascending | ContractorAdmin, Estimator, Adjuster, Customer |
| POST | `/v1/payments/{id}/approve` | Approve a payment; direction-role split; carrier approval requires a signed authorization | Adjuster, ContractorAdmin |
| POST | `/v1/payments/{id}/issue` | Issue an approved payment with the same direction-role split | Adjuster, ContractorAdmin |
| POST | `/v1/payments/{id}/clear` | Clear an issued payment; recomputes counters; may settle the invoice and close the claim | ContractorAdmin |
| POST | `/v1/payments/{id}/return` | Return (bounce or claw back) an issued or cleared payment; counters recomputed | ContractorAdmin |
| POST | `/v1/payments/{id}/requeue` | Re-present a returned payment | ContractorAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_CLAIM_NOT_PAYABLE` | 409 |
| `ERR_SUPPLEMENT_NOT_PERMITTED` | 409 |
| `ERR_ESTIMATE_NOT_EDITABLE` | 409 |
| `ERR_INVOICE_NOT_ISSUABLE` | 409 |
| `ERR_ROUND_NOT_OPEN` | 409 |
| `ERR_AUTHORIZATION_MISSING` | 409 |
| `ERR_CONTAINMENT_REQUIRED` | 422 |
| `ERR_MOISTURE_GATE_FAILED` | 422 |
| `ERR_INSPECTION_INCOMPLETE` | 422 |
| `ERR_INSPECTION_EVIDENCE_INSUFFICIENT` | 422 |
| `ERR_SUPPLEMENT_EVIDENCE_INSUFFICIENT` | 422 |
| `ERR_DUPLICATE_INITIAL_ESTIMATE` | 409 |
| `ERR_DUPLICATE_ACTIVE_INVOICE` | 409 |
| `ERR_INSPECTION_SCHEDULE_CONFLICT` | 409 |
| `ERR_DISPOSITION_LINE_MISMATCH` | 422 |
| `ERR_CODE_UPGRADES_PENDING` | 409 |
| `ERR_PRICE_WINDOW_OVERLAP` | 409 |
| `ERR_POLICY_WINDOW_VIOLATION` | 422 |
| `ERR_PRICE_WINDOW_VIOLATION` | 422 |
| `ERR_AUTHORIZATION_EXPIRED` | 422 |
| `ERR_ORDINANCE_NOT_COVERED` | 422 |
| `ERR_ORDINANCE_CAP_EXHAUSTED` | 422 |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 422 |
| `ERR_DEDUCTIBLE_OVERPAID` | 422 |
