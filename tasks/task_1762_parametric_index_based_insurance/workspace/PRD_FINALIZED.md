# Parametric Index Insurance API — Product Requirements Document

## 1. Introduction

Parametric insurance settles on numbers, not adjusters. When a rainfall index closes a thirty-day window below its strike threshold, every covered policyholder in the region is owed a contractually fixed payout — no loss inspection, no negotiation, no delay. That promise of speed creates its own risks: the product lives or dies on the integrity of the underlying index, on the legal precision of the data-source agreement behind it, on honest disclosure of **basis risk** (the possibility that the index fails to match a customer's actual loss), and on financial controls strong enough to move money automatically without inviting fraud. This document specifies the Parametric Index Insurance API, a system that operates the full settlement lifecycle of an index-based insurance program — index and trigger definition, measurement-station operations, observation ingestion and late revision, event detection and verification, tiered payout calculation, dispute adjudication, and reinsurance recovery.

The system is organized around the **InsuranceProgram** aggregate. Within a program, actuaries define indexes backed by executed data-source agreements, data operations teams commission measurement stations and feed observations, underwriters quote and bind policies priced from the historical distribution of the index, claims adjusters verify trigger events and shepherd claims, treasury officers release payments under a segregation-of-duties regime, fraud analysts police abuse, and program managers govern the program's lifecycle, its reinsurance treaties, and its reporting cadence. State with respect to any measurement window is derived by replaying an ordered, append-only observation log, so a late data revision can reverse conclusions the program has already drawn — and the system is explicit about who bears the cost when that happens.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to declare the capacity in which they act. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Beyond authentication, every write operation is restricted to designated roles; an authenticated operator who attempts an action outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly eight roles, spelled as follows:

- `ProgramManager` — owns the program lifecycle, reinsurance treaties, reporting epochs, and the logical clock.
- `Actuary` — defines indexes, pricing parameters, and regulatory classification inputs; activates and decommissions indexes.
- `Underwriter` — quotes, binds, and cancels policies.
- `ClaimsAdjuster` — verifies trigger events, adjusts, approves, and declines claims, and adjudicates disputes.
- `TreasuryOfficer` — releases claim payments, deliberately segregated from claim approval.
- `FraudAnalyst` — manages fraud signals, blacklists policyholders, and clears fraud holds.
- `DataOperations` — operates measurement stations and ingests index observations.
- `ServicingAgent` — services policyholders: registration, disclosure acknowledgment, premium collection, and dispute intake.

For every one of these roles — `ProgramManager`, `Actuary`, `Underwriter`, `ClaimsAdjuster`, `TreasuryOfficer`, `FraudAnalyst`, `DataOperations`, and `ServicingAgent` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `approver_user_id` on a claim at approval time, where it is later consulted for segregation-of-duties enforcement at payment release) but never compares it to any entity's `id`. Where a workflow needs to remember which capacity opened a record, the role string itself is stored — a dispute case, for instance, preserves its opening capacity in `opened_by_role`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Date-Driven Behaviour

Time in this system is logical, not wall-clock. The server maintains a logical clock that starts at exactly `2026-08-01T00:00:00Z` when the server boots; before any explicit set call, every time-dependent rule reads this default instant, and the server never silently falls back to wall-clock time. A `ProgramManager` may advance the logical clock through an administrative test-driving capability (`POST /_clock/set_current_utc`) that accepts a `to_iso8601` instant (ISO 8601 UTC) and returns the new `current_utc`. Date-driven behaviour — most importantly the expiry sweep that moves a policy to `EXPIRED` once its `policy_end_date` has closed — runs on read against the logical clock, so advancing the clock and then reading a resource is sufficient to observe time-triggered transitions. Temporal validation also reads this clock: an observation whose `window_end_date` lies in the future relative to the logical clock is rejected.

### 2.5. Common Resource Properties

Every primary resource in the system — programs, index definitions, stations, policyholders, policies, trigger events, claims, disputes, treaties, and invoices — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-08-01T09:15:00.123Z`) recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every mutation of the resource, including mutations driven by automatic cascades and computed-aggregate reconciliation.

The single exception is the **IndexObservation** log. Because observations form an append-only event log that is never mutated in place (corrections arrive as new rows that supersede old ones), an observation carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Nested Retrieval, Cross-Aggregate Integrity, and Validation Order

The API enforces a strict, hierarchical validation protocol for every request that targets a nested resource. Paths descend from program to index, station, policyholder, policy, claim, dispute, invoice, treaty, trigger event, or observation, and the system validates path identifiers sequentially from left to right, rejecting immediately with the 404 error that corresponds to the *first* identifier that does not resolve within its parent: `ERR_PROGRAM_NOT_FOUND` for a missing program, then `ERR_INDEX_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_HOLDER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, or `ERR_TREATY_NOT_FOUND` as the position dictates. A request for a station under a non-existent program therefore fails with `ERR_PROGRAM_NOT_FOUND` before the station identifier is ever examined.

Alongside each nested collection, the API exposes flat, program-spanning read endpoints — for example, an index definition, station, policyholder, policy, invoice, trigger event, claim, dispute, or treaty can be fetched directly by its id without walking the parent chain, and flat list endpoints accept filters. These reverse-reachability reads exist so that foreign-key references such as a claim's `trigger_event_id` or a dispute's `claim_id` can be resolved in one call.

When several rules in this document apply to a single request, the server evaluates them in a fixed global order, so that the error surfaced is always the highest-priority failure rather than an arbitrary one:

1. Presence and validity of the user-context headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Left-to-right path existence and nesting (`ERR_PROGRAM_NOT_FOUND` and its siblings above).
4. Whether the parent program's status permits the operation (`ERR_PROGRAM_NOT_ACTIVE`) — policy binding, observation ingestion, and treaty binding all require an `ACTIVE` program.
5. Whether the target entity stands in the state its transition requires (the transition-specific state errors, or `ERR_INVALID_STATE` as the generic state-precondition failure).
6. Segregation of duties at payment release (`ERR_SOD_VIOLATION`).
7. Cross-reference linkability — that a referenced index belongs to the program, a referenced station belongs to the program, or a claim belongs to a policy of a policyholder of the program (`ERR_CROSS_REFERENCE_INVALID`, HTTP 422).
8. Temporal window checks (`ERR_WINDOW_OUT_OF_COVERAGE`).
9. Observation deduplication (`ERR_DUPLICATE_OBSERVATION`).
10. Business constraints: re-verified events must still breach (`ERR_EVENT_NO_LONGER_BREACHING`), claimed tiers must respect the breached envelope (`ERR_TIER_EXCEEDS_BREACH`), and treaty capacity must hold (`ERR_TREATY_CAPACITY_INVALID`).
11. Fiscal gates: premium settlement (`ERR_PREMIUM_NOT_PAID`) and aggregate exposure (`ERR_EXPOSURE_LIMIT_EXCEEDED`); within this level premium settlement is evaluated first, so a bind that would fail both draws `ERR_PREMIUM_NOT_PAID`.
12. The fraud gate on claim approval (`ERR_HOLDER_BLACKLISTED`).

Independent of this ordering, any request with a malformed body, a missing required field, or an invalid enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Precision, Rounding, and Monetary Conventions

All monetary quantities in the system are stored and returned as **integer cents** — premiums, taxes, payouts, cessions, retentions, invoice balances, and treaty positions alike. Whenever a monetary calculation produces a fractional cent, the result is rounded half-up to a whole cent, and the API represents monetary values as numbers, never strings. Two rounding disciplines deserve emphasis because they remove ambiguity at aggregation boundaries. First, reinsurance cession rounds **per treaty** — each treaty's share is rounded half-up to whole cents before the per-treaty shares are summed into the claim's ceded total; the sum is never rounded after the fact. Second, program-level retention rounds **per policy** — each bound policy's ceded share is rounded half-up to whole cents before the retained shares are accumulated.

Index values obey a separate, finer precision. The blended index value computed from station observations is rounded half-up to **4 decimal places**, and it is this four-decimal blend that is compared against trigger thresholds. Configuration and distribution inputs — station reliability weights, historical breach frequencies, expected loss ratios, payout fractions, ceded percentages — preserve the precision they were supplied with.

### 2.8. Optimistic Concurrency Control on the Program

Two write operations against an `InsuranceProgram` are protected by optimistic concurrency control, because both commit on the basis of the program's observed financial state. Each requires the client to supply `expected_program_version`, carrying the program `version` the client last observed; the field is non-optional on these two calls. If the supplied value does not match the program's current `version` — because a bind, a payment release, a treaty binding, or an epoch advance has advanced it since the client last read the program — the request is rejected with `ERR_STALE_VERSION` (HTTP 412):

- **Binding a reinsurance treaty** — another writer may have bound a different treaty in the meantime, legitimately superseding the retention profile the current writer priced against; the writer's view of `net_retained_exposure_cents` is stale and must not silently govern the commit.
- **Closing a program** — any mutation that advanced the program's `version` since the client's last read invalidates the basis on which the close preconditions were checked.

Endpoints other than these two do not take a version field; no other operation performs an OCC check.

### 2.9. Segregation of Duties in Claim Settlement

Approval and payment of a claim are deliberately split across two roles. A `ClaimsAdjuster` approves; a `TreasuryOfficer` releases funds. At approval time, the server records the approving adjuster's `X-User-ID` on the claim as `approver_user_id`. At release time, the releasing officer's `X-User-ID` must differ from the recorded `approver_user_id`; if the same operator identifier attempts both steps, the release is rejected with `ERR_SOD_VIOLATION` (HTTP 403). This control is evaluated after state checks and before any financial mutation, so a self-approved payment never reaches the cession waterfall.

### 2.10. Cascades, Automatic Transitions, and Immediate Consistency

State alignment across the hierarchy is maintained by the server, not left to clients. When a parent transitions in a way that constrains its children, the cascade happens atomically within the same request: suspending a program suspends its active indexes; closing a program expires its still-bound policies and commutes its active treaties; blacklisting a policyholder voids that policyholder's unsettled claims; annulling a verified trigger event declines the claims it generated that have not yet been approved. Cascades also flow upward: a claim entering `APPROVED` or `FRAUD_HOLD` moves its policy's settlement posture to `PAYMENT_PENDING`, and when every claim of a policy reaches a terminal state the posture settles back to `SETTLED_QUIET`. Certain transitions fire automatically when their criteria are satisfied — a policyholder activates upon basis-risk acknowledgment, a treaty exhausts when its recovery cap is reached, a policy expires when its coverage window closes — with no explicit client call on the affected resource. Every such mutation, whether client-initiated or automatic, refreshes `updated_at` and increments `version` on the mutated resource, and all computed program aggregates are reconciled within the same atomic request so that reads never observe a partially applied cascade.

## 3. Business Logic & Workflows

### 3.1. Program Charter, Activation, and Closure

A `ProgramManager` charters a new program by supplying a unique business `program_code`, the covered `peril_type` — one of `RAINFALL_DEFICIT`, `WINDSPEED`, `EARTHQUAKE_MAGNITUDE`, or `TEMPERATURE_EXCESS` — the `regulatory_classification`, the `contract_wording_version` identifying the legal wording template bound to the program, and the `exposure_limit_cents` capping the aggregate net retained exposure the program may carry. The regulatory classification is one of `ADMITTED_INSURANCE`, `SURPLUS_LINES`, or `DERIVATIVE_CONTRACT`, and it is not decorative: it drives the contract wording obligations and, as §3.5 details, selects the expense loading and premium tax tier applied at quotation. Both `regulatory_classification` and `contract_wording_version` are validated as present at creation, because activation later presumes them. A new program begins in `DRAFT` status with its computed aggregates — `gross_written_premium_cents`, `incurred_claims_cents`, `ceded_recovery_cents`, `net_retained_exposure_cents`, and `fraud_alert_count` — all initialized to zero and its `reporting_epoch` at zero.

Activation moves the program from `DRAFT` to `ACTIVE`, and it is gated on substance: at least one of the program's index definitions must already be `ACTIVE`, otherwise the activation is rejected with `ERR_PROGRAM_NO_ACTIVE_INDEX`. An active program can be suspended; suspension requires the program to be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`) and cascades downward, moving every `ACTIVE` index definition of the program to `SUSPENDED`. While a program is suspended, policy binding and trigger detection halt. Resuming reverses the cycle: it requires the program to be `SUSPENDED` (otherwise `ERR_PROGRAM_NOT_SUSPENDED`), returns the program to `ACTIVE`, and cascades every `SUSPENDED` index of the program back to `ACTIVE`.

Closure is the terminal act. A `ProgramManager` closes an `ACTIVE` program by supplying `expected_program_version`; per §2.8, a value that does not match the program's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Close is refused while any claim in the program stands in `GENERATED`, `ADJUSTED`, `APPROVED`, or `FRAUD_HOLD`, and equally while any dispute stands in `OPEN` or `AWAITING_CUSTOMER` — both conditions surface as `ERR_OPEN_CLAIMS_EXIST`. A successful close moves the program to `CLOSED`, expires every policy still `BOUND` (each such policy's settlement posture is left unchanged by the cascade), commutes every `ACTIVE` reinsurance treaty, and increments the program's `version` by one.

Reporting runs on an explicit cadence. An operations run by a `ProgramManager` advances the reporting epoch, incrementing `reporting_epoch` by one and — because it is a program mutation — the program's `version` by one as well. At any point, a computed financial-summary read returns the program's profit-and-loss snapshot as of the current epoch: `gross_written_premium_cents`, `incurred_claims_cents`, `ceded_recovery_cents`, `net_retained_exposure_cents`, `fraud_alert_count`, and `reporting_epoch` together describe the program's standing for reporting and reinsurance-interplay purposes.

### 3.2. Index Design, Data-Source Agreements, and Station Operations

Within a program, an `Actuary` authors an index definition: the instrument against which the program's policies pay. Creation takes the business `index_code`, the physical `measurement_unit` of the index value (millimetres, metres per second, moment magnitude, degrees Celsius), the `aggregation_window_days` giving the length of the rolling measurement window in days, the executed `data_source_agreement_ref` — the legal contract identifier for the data feed, which must be non-empty and is validated as such at creation — the `source_priority_mode`, the `strike_direction`, and the ordered `trigger_thresholds`. The threshold list enumerates severity tiers ascending by severity distance; each entry pairs a `threshold_value` with a `payout_fraction`, where the fraction is greater than 0 and at most 1. The `strike_direction` — `BELOW` or `ABOVE` — fixes the comparison semantics: a `BELOW` index triggers when the blended value is less than or equal to a tier's threshold, an `ABOVE` index when it is greater than or equal. Two pricing inputs ride on the index as well: `historical_breach_frequency`, the observed historical frequency of a tier-1 breach per year from the index distribution, and `expected_loss_ratio`, the expected loss ratio from that same distribution; §3.5 consumes both. Every index definition carries the `program_id` of its owning program and begins life in `PENDING_AGREEMENT` status.

Activation of an index belongs to the `Actuary` and requires the index to be `PENDING_AGREEMENT` (otherwise `ERR_INDEX_NOT_PENDING`). Because an index is only as trustworthy as its feed, activation additionally requires at least one station of the parent program to be `COMMISSIONED`, failing with `ERR_NO_COMMISSIONED_STATION` when the program has none. Once active, an index can be suspended and resumed by a `ProgramManager` — suspension requires `ACTIVE` status (`ERR_INDEX_NOT_ACTIVE`), resumption requires `SUSPENDED` status (`ERR_INDEX_NOT_SUSPENDED`) — and while an index is `SUSPENDED`, observation ingestion on it is rejected, as §3.3 describes. Suspension and resumption also arrive by cascade when the parent program is suspended or resumed. Decommissioning, again an `Actuary` action, is the index's terminal transition; it is refused with `ERR_INDEX_IN_USE` while any policy referencing the index is `BOUND` or while any of the index's trigger events stands in `DETECTED` or `UNDER_REVIEW`. Both nested and flat list reads are available for indexes; the flat collection accepts a `program_id` filter.

The `source_priority_mode` — `STATION_PRIMARY` or `MODEL_PRIMARY` — records which data source wins when station and model disagree, and its consequences play out in the blending rule of §3.3.

Measurement stations are operated by `DataOperations`. Registering one takes the `station_code` from the data-source agreement, the `station_kind` — `PHYSICAL_STATION` or `GRID_MODEL` — and a `reliability_weight` of at least 0.1 and at most 1.0 expressing how much the source counts in the blended index value; model sources typically carry lower weights than physical stations. Each station belongs to a program via its `program_id` and starts `COMMISSIONED`. Taking a station offline requires it to be `COMMISSIONED` (otherwise `ERR_STATION_NOT_COMMISSIONED`) and moves it to `OFFLINE`; while a station is `OFFLINE` — or `DECOMMISSIONED` — new observations attributed to it are rejected. Recommissioning reverses the offline state and requires `OFFLINE` (otherwise `ERR_STATION_NOT_OFFLINE`). Decommissioning is terminal and is permitted from either `COMMISSIONED` (else `ERR_STATION_NOT_COMMISSIONED`) or `OFFLINE` (else `ERR_STATION_NOT_OFFLINE`). Stations, like indexes, expose a flat collection filterable by `program_id`.

### 3.3. Observation Ingestion, Late Revisions, and Event Detection

Observations are the system's source of truth, and they are append-only. A `DataOperations` operator ingests an observation under an index by supplying the producing `station_id`, the `window_end_date` — the ISO date (YYYY-MM-DD) of the last day of the aggregation window — the raw `measured_value` from that station for the window, and, when the row corrects an earlier reading, an optional `supersedes_observation_id`. The server stamps each row with a `sequence_no`, a per-index monotonic ingestion sequence assigned in arrival order, and links it to its `index_definition_id`. Each row also carries a computed `is_effective` flag: true unless and until a later revision for the same station and window supersedes it, at which point the prior row's `is_effective` flips to false. The observation collection is filterable by `window_end_date` and `station_id`; a flat, program-spanning observation list additionally accepts `index_definition_id`.

Ingestion is guarded at several layers. The parent program must be `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`); the index must not be `SUSPENDED` or `DECOMMISSIONED` (`ERR_INDEX_SUSPENDED`); the producing station must not be `OFFLINE` or `DECOMMISSIONED` (`ERR_STATION_OFFLINE`); the referenced station must actually belong to the program (`ERR_CROSS_REFERENCE_INVALID`); and the `window_end_date` must not lie in the future relative to the logical clock (`ERR_WINDOW_OUT_OF_COVERAGE`, HTTP 422). Deduplication is strict: a second observation for the same (`station_id`, `window_end_date`) pair must name the prior effective row in `supersedes_observation_id`, otherwise it is rejected with `ERR_DUPLICATE_OBSERVATION` (HTTP 409). A `supersedes_observation_id` that references no existing observation draws `ERR_OBSERVATION_NOT_FOUND`, and one that references a row other than the currently-effective observation for that station-window pair — a broken correction chain — draws `ERR_SUPERSESSION_CHAIN_BROKEN` (HTTP 409).

Every accepted ingestion recomputes the blended value for its window. The blend draws on the set of effective observations — rows whose `index_definition_id` matches the index, whose `window_end_date` matches the window, and whose `is_effective` flag remains true. Before blending, the source-priority override is applied: when the index is `STATION_PRIMARY` and at least one effective row comes from a `PHYSICAL_STATION`, all `GRID_MODEL` rows are excluded from the blend; symmetrically, a `MODEL_PRIMARY` index with at least one effective `GRID_MODEL` row excludes physical-station rows. The blended value is then the weighted mean of the surviving rows — each `measured_value` multiplied by its station's `reliability_weight`, summed, and divided by the sum of those weights — rounded half-up to 4 decimal places. If the effective set for the window is empty, the blend fails; at verification time this surfaces as `ERR_EVENT_NO_LONGER_BREACHING`.

The blended value is tested against the index's tiers. Under `BELOW` direction, a tier breaches when the blend is less than or equal to its `threshold_value`; under `ABOVE`, when the blend is greater than or equal. The boundary is inclusive — a value exactly at the threshold breaches the tier. The highest breaching tier becomes the window's `max_tier_breached`, with 0 signifying that no tier breached.

Two automatic consequences follow. When the recomputed blend breaches tier 1 or higher and no trigger event yet exists for that index and window, the system creates a trigger event in `DETECTED` status, copying the `window_end_date` from the decisive observation and recording the computed `blended_index_value`, the `max_tier_breached`, and the `verification_method` — `STATION_VERIFIED` or `MODEL_FALLBACK`, decided by the index's `source_priority_mode` and the availability of station data for the window. The event carries its `index_definition_id` and a denormalized `program_id` for aggregate queries. When, instead, a `VERIFIED` event already exists for the window and a late revision moves the blend so that `max_tier_breached` falls to 0, the event is automatically annulled — the compensation cascade of §3.6 then unwinds the claims it spawned.

### 3.4. Policyholder Onboarding, Basis-Risk Disclosure, and Fraud Signals

A `ServicingAgent` registers a policyholder within a program by supplying the `legal_name` and `tax_id`, optionally recording `basis_risk_disclosure_acknowledged` at the same time. Parametric products obligate the insurer to explain basis risk — the structural gap between the index and the customer's actual loss — and the system refuses to treat a policyholder as fully onboarded until that explanation has been acknowledged. A new policyholder therefore starts as a `PROSPECT`, with `basis_risk_disclosure_acknowledged` defaulting to false; if the acknowledgment is supplied as true at creation, the status flips to `ACTIVE` automatically. Later, a servicing update to the record (which may also revise `legal_name`) that flips the acknowledgment from false to true while the holder is a `PROSPECT` activates the holder in the same automatic fashion. Activation has no path around the acknowledgment — any attempt to move a policyholder to `ACTIVE` without it is rejected with `ERR_BASIS_RISK_NOT_ACKNOWLEDGED`. Every policyholder carries the `program_id` of the owning program, and the flat policyholder collection can be filtered by `program_id` and `status`.

Each policyholder also accumulates a computed `fraud_score`, starting at 0. Two forces raise it: a manual flag by a `FraudAnalyst` adds 25 points, and — as §3.8 details — each dispute resolved `DENIED` on a `DATA_SOURCE_ERROR` challenge adds 10 points, on the reasoning that frivolous data challenges are a contagion signal. The score is clamped to the range 0 through 100 inclusive. Once a policyholder's `fraud_score` reaches 70, the approval gate of §3.7 stops letting their claims pass directly to `APPROVED` and routes them to `FRAUD_HOLD` instead.

Blacklisting is the fraud team's hard sanction. A `FraudAnalyst` may blacklist a policyholder who is `ACTIVE` or `PROSPECT`; any other starting state is rejected with `ERR_HOLDER_NOT_ACTIVE`. Blacklisting an `ACTIVE` policyholder cascades across the book: every claim of that policyholder standing in `GENERATED` or `ADJUSTED` is voided, while claims already `APPROVED` are unaffected — they are committed to treasury and must run their course. Blacklisting a `PROSPECT`, who can hold no claims, carries no cascade.

### 3.5. Quotation, Premium Pricing, Invoicing, and Binding

An `Underwriter` quotes a policy for a policyholder by submitting the `index_definition_id` the policy triggers on, the `sum_insured_cents` limit, and the coverage dates `policy_start_date` and `policy_end_date` — both ISO dates, both inclusive, with the end date strictly after the start date. The referenced index must belong to the program under which the policy is written; a cross-program reference is rejected with `ERR_CROSS_REFERENCE_INVALID`. The new policy opens with `lifecycle_status` `QUOTED` and `settlement_posture` `CLEAR`, records its `policyholder_id` and a denormalized `program_id` for aggregate queries, and is priced immediately from the index distribution.

Pricing proceeds in a pinned order. The pure premium is `sum_insured_cents` multiplied by the index's `historical_breach_frequency` and then by its `expected_loss_ratio`. The program's `regulatory_classification` then selects an expense loading — 25% for `ADMITTED_INSURANCE`, 35% for `SURPLUS_LINES`, 15% for `DERIVATIVE_CONTRACT` — and `premium_cents` is the pure premium multiplied by one plus that loading rate, rounded half-up to a whole cent. Finally, tax is levied on the loaded premium, never on the pure premium: `premium_tax_cents` is `premium_cents` multiplied by the classification's tax rate — 2% for `ADMITTED_INSURANCE`, 5% for `SURPLUS_LINES`, and 0% for `DERIVATIVE_CONTRACT` — rounded half-up to a whole cent.

Quotation simultaneously issues the policy's premium invoice. The invoice is created in `ISSUED` status with `invoice_amount_cents` equal to the sum of `premium_cents` and `premium_tax_cents` computed at issuance, an `amount_paid_cents` of zero, and a `due_date` equal to the policy's start date — coverage binds only when the invoice is fully paid by that due date. A `ServicingAgent` applies payments against an invoice by submitting an `amount_cents`; the invoice must be `ISSUED` or `PARTIALLY_PAID` (otherwise `ERR_INVOICE_NOT_PAYABLE`), the amount must be greater than zero, and the running `amount_paid_cents` plus the new amount must not exceed `invoice_amount_cents` — an overpaying submission is rejected with `ERR_OVERPAYMENT` (HTTP 422). Each accepted payment adds to `amount_paid_cents`; the invoice stands `PARTIALLY_PAID` while a balance remains and turns `PAID` the moment payments equal the billed amount. Should the policy be cancelled before binding, the system voids the still-open invoice. Invoices are listable within a program or across programs, filterable by `policy_id` and `status`.

Binding converts a quote into cover, and it is the most heavily guarded transition in the system. The policy must be `QUOTED` (`ERR_POLICY_NOT_QUOTED`); the policyholder must be `ACTIVE` (`ERR_HOLDER_NOT_ACTIVE_FOR_BIND`); the parent program must be `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`); the referenced index must be `ACTIVE` (`ERR_INDEX_NOT_ACTIVE`); the policy's invoice must be `PAID` (`ERR_PREMIUM_NOT_PAID`, HTTP 402); and the book must retain headroom — after accounting for the new policy, the program's `net_retained_exposure_cents` must remain less than or equal to `exposure_limit_cents`, otherwise the bind is rejected with `ERR_EXPOSURE_LIMIT_EXCEEDED` (HTTP 402). The retention figure itself is computed per §3.9's rule: across the program's `BOUND` policies, each policy contributes its `sum_insured_cents` minus its ceded share, where the ceded share is `sum_insured_cents` multiplied by the total active ceded percentage and divided by 100, rounded half-up per policy before summing. On a successful bind the policy's `lifecycle_status` becomes `BOUND`, the program's `gross_written_premium_cents` grows by the policy's `premium_cents` — a figure that accumulates over every policy ever bound and is never decremented, even by later cancellation or expiry — and `net_retained_exposure_cents` is recomputed to include the new policy's retained share.

Cancellation is available to the `Underwriter` only while the commitment is still clean: the policy must be `BOUND` (`ERR_POLICY_NOT_BOUND`), its `settlement_posture` must not be `PAYMENT_PENDING` (`ERR_POLICY_PAYMENT_IN_FLIGHT`), and it must hold no claim in `GENERATED`, `ADJUSTED`, `APPROVED`, `FRAUD_HOLD`, or `PAID` (`ERR_POLICY_HAS_CLAIMS`). A cancelled policy moves to `CANCELLED` and its retained share leaves `net_retained_exposure_cents` by recomputation. Expiry requires no action: when the logical clock carries the calendar past `policy_end_date`, the on-read sweep moves a `BOUND` policy to `EXPIRED` and recomputes retention without its share; the program-close cascade of §3.1 expires still-bound policies the same way. Policies can be listed per policyholder, per program, or flat across programs, with the program-scoped and flat collections accepting `index_definition_id`, `policyholder_id`, `program_id`, and `lifecycle_status` filters.

The settlement posture evolves in parallel with, and independently of, the lifecycle. A policy starts `CLEAR`; the moment any of its claims enters `APPROVED` or `FRAUD_HOLD`, the posture bubbles up to `PAYMENT_PENDING`; when every claim of the policy has reached a terminal state — `PAID`, `RECOVERY_CEDED`, `DECLINED`, or `VOIDED` — the posture settles to `SETTLED_QUIET`; and if a new claim is later `GENERATED` for a quiet policy, as happens when a late event lands after the book seemed closed, the posture returns to `PAYMENT_PENDING`. Claim operations key off this dimension: most visibly, cancellation is barred while payment is in flight.

### 3.6. Event Verification and Claim Generation

Detection is automatic; payment is not. A trigger event born in `DETECTED` status waits for a `ClaimsAdjuster` to open a verification review, which requires the event to be `DETECTED` (otherwise `ERR_EVENT_NOT_DETECTED`) and moves it to `UNDER_REVIEW`. Trigger events are listable per index or across the program, filterable by `status`, `index_definition_id`, and `program_id`.

Verification is where the system replays the evidence. The adjuster's verify action requires the event to be `UNDER_REVIEW` (otherwise `ERR_EVENT_NOT_UNDER_REVIEW`) and recomputes the window from the effective observation set: the blend is re-derived by chronological replay of the effective observations per §3.3's weighted rule, and `blended_index_value` and `max_tier_breached` are recomputed and stored. If the recomputed blend no longer breaches at least tier 1 — whether because a late revision moved the index or because the effective set has gone empty — verification fails with `ERR_EVENT_NO_LONGER_BREACHING` (HTTP 409) and the event stays under review. Rejection is the adjuster's other verdict from `UNDER_REVIEW` (same `ERR_EVENT_NOT_UNDER_REVIEW` guard): the event becomes `REJECTED` and no claims are generated.

A successful verification moves the event to `VERIFIED` and fans out across the book. For every policy `BOUND` on this index whose coverage window — `policy_start_date` through `policy_end_date`, both inclusive — contains the event's `window_end_date`, the system generates exactly one claim, producing them in the order the policies were created; a policy whose window does not contain the window end date contributes no claim (this is the claim-generation side of `ERR_WINDOW_OUT_OF_COVERAGE`). Each generated claim opens in `GENERATED` status, linked to its `policy_id` and the `trigger_event_id` that spawned it, with `tier_applied` defaulted to the event's `max_tier_breached`, `ceded_recovery_cents` at zero, and `provisional_payout_cents` computed forward-looking: the policy's `sum_insured_cents` multiplied by the `payout_fraction` of `tier_applied`, rounded half-up to a whole cent, with no regard to any other claim of the same policy in the same coverage year. Claim generation alone does not disturb a policy's settlement posture — the posture moves only when a claim later reaches `APPROVED` or `FRAUD_HOLD`.

Annulment is verification's mirror. When a late observation revision drops a `VERIFIED` event's recomputed `max_tier_breached` to 0, the system moves the event to `ANNULLED` without any client call. Compensation follows immediately: every claim generated from the event that still stands in `GENERATED` or `ADJUSTED` is declined, while claims already `APPROVED` are deliberately left standing — money that far committed must be clawed back through the dispute process of §3.8, not auto-voided. The settlement posture of every affected policy is re-evaluated in the same pass.

### 3.7. Claim Adjustment, Approval, Fraud Hold, and Payment Release

A generated claim is a starting position, not a verdict. A `ClaimsAdjuster` may adjust a claim standing in `GENERATED` or `ADJUSTED` — anything else draws `ERR_CLAIM_NOT_ADJUSTABLE` — and only while the claim's trigger event is `VERIFIED` (`ERR_EVENT_NOT_VERIFIED`). The adjustment submits a `new_tier`, which must be at least 1, must not exceed the event's `max_tier_breached`, and must differ from the claim's current `tier_applied`; any of the three violations is rejected with `ERR_TIER_EXCEEDS_BREACH` (HTTP 422). A valid adjustment replaces `tier_applied`, recomputes `provisional_payout_cents` on the same forward-looking formula, and lands the claim in `ADJUSTED` — a state that permits further adjustment loops.

Approval is the point of financial commitment. The adjuster's approve action requires the claim to be `GENERATED` or `ADJUSTED` (`ERR_CLAIM_NOT_ADJUSTABLE`), the trigger event `VERIFIED` (`ERR_EVENT_NOT_VERIFIED`), the policy `BOUND` (`ERR_POLICY_NOT_BOUND`), and the policyholder not `BLACKLISTED` — a blacklisted holder blocks approval outright with `ERR_HOLDER_BLACKLISTED` (HTTP 403). When those guards pass, the server records the approving adjuster's user identifier in the claim's `approver_user_id` for the segregation-of-duties check of §2.9, and computes `final_payout_cents` on the chronological, capped variant — which can differ from the provisional figure. The computation first sums the `final_payout_cents` of every other claim of the same policy that stands in `APPROVED`, `PAID`, or `RECOVERY_CEDED` and belongs to the same coverage year, where the coverage year is the calendar year of the triggering event's `window_end_date`. It then computes the uncapped amount — `sum_insured_cents` multiplied by the `payout_fraction` of `tier_applied`, rounded half-up to a whole cent — and sets `final_payout_cents` to the smaller of that uncapped amount and the remaining per-policy headroom, namely `sum_insured_cents` minus the prior sum, with the headroom floored at zero. The claim moves to `APPROVED`, and the policy's settlement posture bubbles up to `PAYMENT_PENDING`.

The fraud gate sits directly on this path. When an approve attempt targets a claim whose policyholder's `fraud_score` has reached 70, the claim does not become `APPROVED`; it is routed to `FRAUD_HOLD` instead, the program's `fraud_alert_count` is incremented by one, and the policy posture still rises to `PAYMENT_PENDING`. A claim under fraud hold waits for the fraud team: a `FraudAnalyst` clears the hold on a claim standing in `FRAUD_HOLD` (otherwise `ERR_CLAIM_NOT_IN_FRAUD_HOLD`), which moves the claim to `APPROVED`, decrements `fraud_alert_count` by one, and recomputes `final_payout_cents` on the same chronological capped formula, so clearance never inherits stale numbers.

Payment release belongs to the `TreasuryOfficer` alone and requires the claim to be `APPROVED` (`ERR_CLAIM_NOT_APPROVED`). Segregation of duties is then enforced exactly as §2.9 states: the releasing officer's identifier must differ from the recorded `approver_user_id`, or the release is rejected with `ERR_SOD_VIOLATION` (HTTP 403). A successful release runs the reinsurance cession waterfall. The program's `ACTIVE` treaties are processed in the order they were created — creation is sequential and timestamps are distinct, so ties cannot occur, but if one somehow did the order remains creation order and never falls back to comparing ids. For each treaty, the excess over attachment is the claim's `final_payout_cents` minus the treaty's `attachment_point_cents`, floored at zero; the gross cession is that excess multiplied by the treaty's `ceded_percentage` and divided by 100, rounded half-up to a whole cent; the treaty's remaining room is its `treaty_limit_cents` minus its `recovered_to_date_cents`; and the amount actually ceded to that treaty is the smaller of the gross cession and the remaining room, floored at zero. Each treaty's `recovered_to_date_cents` grows by its ceded share, and a treaty whose cumulative recovery reaches its `treaty_limit_cents` exactly is exhausted on the spot — its status becomes `EXHAUSTED` and it takes no further cessions. The claim's `ceded_recovery_cents` is the sum of the per-treaty cessions (rounded per treaty before summing, per §2.7), its `net_payment_cents` is `final_payout_cents` minus `ceded_recovery_cents`, and its final status is `RECOVERY_CEDED` when any amount was ceded, `PAID` when none was. In the same atomic step the program's `incurred_claims_cents` grows by the claim's `final_payout_cents`, the program's `ceded_recovery_cents` grows by the claim's ceded total, and if every claim of the policy has now reached a terminal state the policy's posture settles to `SETTLED_QUIET`.

Decline is the adjuster's negative verdict: a claim in `GENERATED` or `ADJUSTED` (`ERR_CLAIM_NOT_ADJUSTABLE`) moves to `DECLINED`, whether by the adjuster's own action or by the annulment cascade of §3.6, and the policy's posture is re-evaluated. The blacklist cascade of §3.4 likewise terminates unsettled claims, moving them to `VOIDED` with the same posture re-evaluation. Claims are listable within a program — including a per-policy listing — or flat across programs, filterable by `policy_id`, `trigger_event_id`, and `status`.

### 3.8. Disputes, Basis-Risk Remedies, and Post-Settlement Adjustment

Settlement is not the end of the conversation. A `ServicingAgent` may open a dispute on behalf of a policyholder against a claim that has reached a settled outcome — `PAID`, `RECOVERY_CEDED`, or `DECLINED`; an attempt against a claim in any other state is rejected with `ERR_CLAIM_NOT_SETTLED`. The intake captures the `dispute_reason` — one of `BASIS_RISK_MISMATCH`, `DATA_SOURCE_ERROR`, `THRESHOLD_BOUNDARY`, or `LATE_REVISION` — and the `claimed_tier` the policyholder asserts should have applied. The dispute opens in `OPEN` status, records the opening capacity in `opened_by_role`, links to its `claim_id`, and starts with `resolution` `NONE` and an `adjustment_delta_cents` of zero. Disputes are listable per claim or flat, filterable by `claim_id` and `status`.

The dialogue has a defined rhythm. A `ClaimsAdjuster` who needs more from the customer sends the dispute from `OPEN` to `AWAITING_CUSTOMER` (any other state draws `ERR_DISPUTE_NOT_OPEN`); the `ServicingAgent` returns it to `OPEN` by submitting the requested information (which requires `AWAITING_CUSTOMER`, else `ERR_DISPUTE_NOT_AWAITING`); and this cycle between `OPEN` and `AWAITING_CUSTOMER` may repeat as many times as the exchange requires. Withdrawal by the `ServicingAgent` is available from either `OPEN` or `AWAITING_CUSTOMER`, moves the dispute to `WITHDRAWN`, and carries no financial effect.

Resolution is the `ClaimsAdjuster`'s call from either `OPEN` or `AWAITING_CUSTOMER` (`ERR_DISPUTE_NOT_OPEN` otherwise), and because disputes adjudicate settled outcomes, the underlying claim must stand in `PAID`, `RECOVERY_CEDED`, or `DECLINED`. The submitted `resolution` must be one of `UPHELD`, `PARTIAL_UPHELD`, or `DENIED`, and a successful resolution moves the dispute to `RESOLVED` with the outcome recorded in `resolution`. Before any money moves, the asserted `claimed_tier` is validated: it must be at least 1, must not exceed the triggering event's `max_tier_breached`, and must differ from the claim's current `tier_applied` — violations are rejected with `ERR_TIER_EXCEEDS_BREACH`. The remedy benchmark is the payout the asserted tier would have produced: `sum_insured_cents` multiplied by the `payout_fraction` of `claimed_tier`, rounded half-up to a whole cent. On `UPHELD`, `adjustment_delta_cents` is that benchmark minus the claim's `final_payout_cents`. On `PARTIAL_UPHELD`, the delta is half of that same difference, rounded half-up to a whole cent. On `DENIED`, the delta is zero. The signed delta applies to the claim's `final_payout_cents` and to the program's `incurred_claims_cents` alike — a downward adjustment reduces both — while cession is deliberately not re-run on adjustment: the claim's `ceded_recovery_cents` stands, and its `net_payment_cents` is recomputed simply as the revised `final_payout_cents` minus the unchanged `ceded_recovery_cents`.

One resolution path feeds the fraud model. When a dispute is resolved `DENIED` and its `dispute_reason` was `DATA_SOURCE_ERROR`, the policyholder's `fraud_score` is increased by 10, clamped within the 0-to-100 band of §3.4 — frivolous challenges to the data feed are treated as a contagion signal that nudges the holder toward the automatic hold threshold.

### 3.9. Reinsurance Treaties and Ceded Recovery

Programs lay off risk through quota-share treaties. A `ProgramManager` creates a treaty proposal by supplying the `treaty_name`, the `ceded_percentage` ceded to the reinsurer — which must be greater than 0 and at most 100, with violations rejected as `ERR_TREATY_CAPACITY_INVALID` (HTTP 422) — the per-event `attachment_point_cents` below which the treaty shares nothing, and the aggregate `treaty_limit_cents` capping total recoveries under the treaty. The proposal opens in `PROPOSED` status with `recovered_to_date_cents` at zero, carrying its `program_id`; cumulative recoveries can never exceed the treaty limit. Treaties are listable within a program or flat, filterable by `program_id` and `status`.

Binding a treaty is a program-level financial commitment and therefore carries the concurrency guard of §2.8: the request must supply `expected_program_version` matching the program's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). The treaty must still be `PROPOSED` (`ERR_TREATY_NOT_PROPOSED`) and the program must be `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`). A successful binding moves the treaty to `ACTIVE`, increments the program's `version` by one, and recomputes `net_retained_exposure_cents` — cession lowers retention, because the program now shares each bound policy's limit with the reinsurer.

The retention figure governed by `exposure_limit_cents` is computed as follows. Let the total active ceded percentage be the sum of `ceded_percentage` over the program's `ACTIVE` treaties, capped at 100. Then, walking the program's `BOUND` policies in creation order for determinism, each policy's ceded share is its `sum_insured_cents` multiplied by that total percentage and divided by 100, rounded half-up to a whole cent per policy, and each policy contributes its `sum_insured_cents` minus its ceded share to the retention. The sum of those retained amounts is `net_retained_exposure_cents`, recomputed on every bind, cancellation, expiry, and treaty binding.

Two terminal transitions complete the treaty lifecycle, both automatic. A treaty whose `recovered_to_date_cents` reaches its `treaty_limit_cents` during a claim cession is immediately `EXHAUSTED`, taking no further cessions. And when the program closes, every `ACTIVE` treaty is `COMMUTED` as part of the closure cascade of §3.1.

## 4. Endpoint Definitions

Operations that create a new resource — a program, an index definition, a station, an observation, a policyholder, a policy, a dispute, or a treaty — return `201 Created`. Operations that act on an existing resource without creating a new one — lifecycle transitions, payments, updates, approvals, releases — return `200 OK`. All resources are grouped under the `/programs` prefix, except the administrative logical-clock capability. Readers should reconstruct each endpoint's request payload and side effects from the workflow narratives of §3; this table is intentionally limited to routing and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC) | ProgramManager |
| POST | `/programs` | Create an insurance program | ProgramManager |
| GET | `/programs` | List programs | Any |
| GET | `/programs/{programId}` | Get one program | Any |
| POST | `/programs/{programId}/activate` | Activate a program (requires at least one ACTIVE index) | ProgramManager |
| POST | `/programs/{programId}/suspend` | Suspend a program; cascades indexes to SUSPENDED | ProgramManager |
| POST | `/programs/{programId}/resume` | Resume a program; cascades indexes back to ACTIVE | ProgramManager |
| POST | `/programs/{programId}/close` | Close a program (OCC on `expected_program_version`) | ProgramManager |
| POST | `/programs/{programId}/advance-reporting-epoch` | Advance the program's reporting epoch | ProgramManager |
| POST | `/programs/{programId}/index-definitions` | Create an index/trigger definition with data-source agreement | Actuary |
| GET | `/programs/{programId}/index-definitions` | List index definitions of a program | Any |
| GET | `/programs/{programId}/index-definitions/{indexId}` | Get one index definition | Any |
| POST | `/programs/{programId}/index-definitions/{indexId}/activate` | Activate an index (requires a COMMISSIONED station) | Actuary |
| POST | `/programs/{programId}/index-definitions/{indexId}/suspend` | Suspend an index | ProgramManager |
| POST | `/programs/{programId}/index-definitions/{indexId}/resume` | Resume an index | ProgramManager |
| POST | `/programs/{programId}/index-definitions/{indexId}/decommission` | Decommission an index (no BOUND policies, no open events) | Actuary |
| GET | `/programs/index-definitions` | Filtered list of index definitions across programs | Any |
| GET | `/programs/index-definitions/{indexId}` | Get one index definition by id (flat) | Any |
| POST | `/programs/{programId}/stations` | Register a measurement station or grid model | DataOperations |
| GET | `/programs/{programId}/stations` | List stations of a program | Any |
| GET | `/programs/{programId}/stations/{stationId}` | Get one station | Any |
| POST | `/programs/{programId}/stations/{stationId}/take-offline` | Take a station offline | DataOperations |
| POST | `/programs/{programId}/stations/{stationId}/recommission` | Recommission an offline station | DataOperations |
| POST | `/programs/{programId}/stations/{stationId}/decommission` | Decommission a station | DataOperations |
| GET | `/programs/stations` | Filtered list of stations across programs | Any |
| GET | `/programs/stations/{stationId}` | Get one station by id (flat) | Any |
| POST | `/programs/{programId}/index-definitions/{indexId}/observations` | Ingest an index observation (or a revision) | DataOperations |
| GET | `/programs/{programId}/index-definitions/{indexId}/observations` | List observations of an index | Any |
| GET | `/programs/observations` | Filtered list of observations across indexes | Any |
| GET | `/programs/observations/{observationId}` | Get one observation by id (flat) | Any |
| POST | `/programs/{programId}/policyholders` | Register a policyholder | ServicingAgent |
| GET | `/programs/{programId}/policyholders` | List policyholders of a program | Any |
| GET | `/programs/{programId}/policyholders/{holderId}` | Get one policyholder | Any |
| PATCH | `/programs/{programId}/policyholders/{holderId}` | Update a policyholder (e.g., acknowledge basis-risk disclosure) | ServicingAgent |
| POST | `/programs/{programId}/policyholders/{holderId}/blacklist` | Blacklist a policyholder; voids unsettled claims | FraudAnalyst |
| POST | `/programs/{programId}/policyholders/{holderId}/flag-fraud` | Record a manual fraud signal against a policyholder | FraudAnalyst |
| GET | `/programs/policyholders` | Filtered list of policyholders across programs | Any |
| GET | `/programs/policyholders/{holderId}` | Get one policyholder by id (flat) | Any |
| POST | `/programs/{programId}/policyholders/{holderId}/policies` | Quote a parametric policy; creates the premium invoice | Underwriter |
| GET | `/programs/{programId}/policyholders/{holderId}/policies` | List policies of a policyholder | Any |
| GET | `/programs/{programId}/policyholders/{holderId}/policies/{policyId}` | Get one policy | Any |
| POST | `/programs/{programId}/policyholders/{holderId}/policies/{policyId}/bind` | Bind a quoted policy | Underwriter |
| POST | `/programs/{programId}/policyholders/{holderId}/policies/{policyId}/cancel` | Cancel a bound policy with no claims and no payment in flight | Underwriter |
| GET | `/programs/{programId}/policies` | Filtered list of policies within a program | Any |
| GET | `/programs/policies` | Filtered list of policies across programs | Any |
| GET | `/programs/policies/{policyId}` | Get one policy by id (flat) | Any |
| GET | `/programs/{programId}/invoices` | Filtered list of premium invoices of a program | Any |
| GET | `/programs/{programId}/invoices/{invoiceId}` | Get one invoice | Any |
| POST | `/programs/{programId}/invoices/{invoiceId}/payments` | Apply a premium payment (partial allowed) | ServicingAgent |
| GET | `/programs/invoices` | Filtered list of premium invoices across programs | Any |
| GET | `/programs/invoices/{invoiceId}` | Get one invoice by id (flat) | Any |
| GET | `/programs/{programId}/index-definitions/{indexId}/trigger-events` | List trigger events of an index | Any |
| GET | `/programs/{programId}/index-definitions/{indexId}/trigger-events/{eventId}` | Get one trigger event | Any |
| GET | `/programs/{programId}/trigger-events` | Filtered list of trigger events within a program | Any |
| POST | `/programs/{programId}/index-definitions/{indexId}/trigger-events/{eventId}/open-review` | Open verification review on a detected event | ClaimsAdjuster |
| POST | `/programs/{programId}/index-definitions/{indexId}/trigger-events/{eventId}/verify` | Verify an event; recompute blend and generate claims | ClaimsAdjuster |
| POST | `/programs/{programId}/index-definitions/{indexId}/trigger-events/{eventId}/reject` | Reject a detected event (no claims) | ClaimsAdjuster |
| GET | `/programs/trigger-events` | Filtered list of trigger events across programs | Any |
| GET | `/programs/trigger-events/{eventId}` | Get one trigger event by id (flat) | Any |
| GET | `/programs/{programId}/claims` | Filtered list of claims within a program | Any |
| GET | `/programs/{programId}/claims/{claimId}` | Get one claim | Any |
| GET | `/programs/{programId}/policyholders/{holderId}/policies/{policyId}/claims` | List claims of a policy | Any |
| POST | `/programs/{programId}/claims/{claimId}/adjust` | Adjust a claim's tier; recomputes the provisional payout | ClaimsAdjuster |
| POST | `/programs/{programId}/claims/{claimId}/approve` | Approve a claim (or auto-route to fraud hold) | ClaimsAdjuster |
| POST | `/programs/{programId}/claims/{claimId}/decline` | Decline a GENERATED/ADJUSTED claim | ClaimsAdjuster |
| POST | `/programs/{programId}/claims/{claimId}/clear-fraud-hold` | Clear a fraud hold after investigation | FraudAnalyst |
| POST | `/programs/{programId}/claims/{claimId}/release-payment` | Release payment; runs the cession waterfall; SoD enforced | TreasuryOfficer |
| GET | `/programs/claims` | Filtered list of claims across programs | Any |
| GET | `/programs/claims/{claimId}` | Get one claim by id (flat) | Any |
| POST | `/programs/{programId}/claims/{claimId}/disputes` | Open a basis-risk dispute on a settled claim | ServicingAgent |
| GET | `/programs/{programId}/claims/{claimId}/disputes` | List disputes of a claim | Any |
| GET | `/programs/{programId}/claims/{claimId}/disputes/{disputeId}` | Get one dispute | Any |
| POST | `/programs/{programId}/claims/{claimId}/disputes/{disputeId}/request-info` | Request more information from the customer | ClaimsAdjuster |
| POST | `/programs/{programId}/claims/{claimId}/disputes/{disputeId}/submit-info` | Submit the requested information | ServicingAgent |
| POST | `/programs/{programId}/claims/{claimId}/disputes/{disputeId}/resolve` | Resolve a dispute; applies the signed adjustment | ClaimsAdjuster |
| POST | `/programs/{programId}/claims/{claimId}/disputes/{disputeId}/withdraw` | Withdraw a dispute | ServicingAgent |
| GET | `/programs/disputes` | Filtered list of disputes across claims | Any |
| GET | `/programs/disputes/{disputeId}` | Get one dispute by id (flat) | Any |
| POST | `/programs/{programId}/treaties` | Create a quota-share treaty proposal | ProgramManager |
| GET | `/programs/{programId}/treaties` | List treaties of a program | Any |
| GET | `/programs/{programId}/treaties/{treatyId}` | Get one treaty | Any |
| POST | `/programs/{programId}/treaties/{treatyId}/bind-treaty` | Bind a treaty (OCC on `expected_program_version`) | ProgramManager |
| GET | `/programs/treaties` | Filtered list of treaties across programs | Any |
| GET | `/programs/treaties/{treatyId}` | Get one treaty by id (flat) | Any |
| GET | `/programs/{programId}/financial-summary` | Computed program P&L snapshot for reporting and reinsurance interplay | Any |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier the API can return. Trigger conditions are defined in the narratives of §2 and §3; this table intentionally carries only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_INDEX_NOT_FOUND` | 404 Not Found |
| `ERR_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_HOLDER_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_DISPUTE_NOT_FOUND` | 404 Not Found |
| `ERR_TREATY_NOT_FOUND` | 404 Not Found |
| `ERR_OBSERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_NOT_SUSPENDED` | 409 Conflict |
| `ERR_PROGRAM_NO_ACTIVE_INDEX` | 409 Conflict |
| `ERR_OPEN_CLAIMS_EXIST` | 409 Conflict |
| `ERR_INDEX_NOT_PENDING` | 409 Conflict |
| `ERR_INDEX_NOT_ACTIVE` | 409 Conflict |
| `ERR_INDEX_NOT_SUSPENDED` | 409 Conflict |
| `ERR_INDEX_IN_USE` | 409 Conflict |
| `ERR_NO_COMMISSIONED_STATION` | 409 Conflict |
| `ERR_STATION_NOT_COMMISSIONED` | 409 Conflict |
| `ERR_STATION_NOT_OFFLINE` | 409 Conflict |
| `ERR_STATION_OFFLINE` | 409 Conflict |
| `ERR_INDEX_SUSPENDED` | 409 Conflict |
| `ERR_DUPLICATE_OBSERVATION` | 409 Conflict |
| `ERR_SUPERSESSION_CHAIN_BROKEN` | 409 Conflict |
| `ERR_BASIS_RISK_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_HOLDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_HOLDER_NOT_ACTIVE_FOR_BIND` | 409 Conflict |
| `ERR_HOLDER_BLACKLISTED` | 403 Forbidden |
| `ERR_POLICY_NOT_QUOTED` | 409 Conflict |
| `ERR_POLICY_NOT_BOUND` | 409 Conflict |
| `ERR_POLICY_HAS_CLAIMS` | 409 Conflict |
| `ERR_POLICY_PAYMENT_IN_FLIGHT` | 409 Conflict |
| `ERR_PREMIUM_NOT_PAID` | 402 Payment Required |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_EXPOSURE_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_EVENT_NOT_DETECTED` | 409 Conflict |
| `ERR_EVENT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_EVENT_NOT_VERIFIED` | 409 Conflict |
| `ERR_EVENT_NO_LONGER_BREACHING` | 409 Conflict |
| `ERR_WINDOW_OUT_OF_COVERAGE` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_ADJUSTABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_CLAIM_NOT_IN_FRAUD_HOLD` | 409 Conflict |
| `ERR_CLAIM_NOT_SETTLED` | 409 Conflict |
| `ERR_TIER_EXCEEDS_BREACH` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_DISPUTE_NOT_OPEN` | 409 Conflict |
| `ERR_DISPUTE_NOT_AWAITING` | 409 Conflict |
| `ERR_TREATY_NOT_PROPOSED` | 409 Conflict |
| `ERR_TREATY_CAPACITY_INVALID` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CROSS_REFERENCE_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
