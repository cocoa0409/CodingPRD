# Health Plan Provider Contracting API — Product Requirements Document

## 1. Introduction

Health plans live and die by the accuracy of their provider agreements. Every contracted rate — whether expressed as a percentage of the Medicare benchmark, a flat amount, a per-diem, or a case rate — must be negotiated, memorialized, loaded against the correct Medicare locality and year, tested against realistic claims, and activated on a precise effective date. Amendments routinely arrive with retroactive reach, forcing the plan to re-adjudicate claims that were already paid under superseded rates. Regulators and internal pricing policy impose further discipline: contracted percentages may not fall below a floor relative to Medicare, and the same provider's rates may not drift too far apart across the plan's commercial, Medicare Advantage, and Medicaid products.

This API is the system of record for that entire contracting lifecycle. It governs reference data (networks, Medicare benchmarks, rate parity rules), provider registration, contract drafting and a negotiation cycle with segregated signature authority, fee schedule construction with benchmark mapping and contract-language carve-outs, pre-go-live claim simulation with a quantitative pass gate, go-live approval with cross-product rate parity enforcement, a paid-claim ledger supporting retroactive adjustment runs through adjudication and settlement, and termination with a minimum notice period and continuity-of-care protection for members in active treatment. Every material event in a contract's lifetime lands in an append-only, per-contract audit trail, and every cent of downstream payment logic traces back to a version that was validated, tested, and approved before it ever priced a claim.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must carry `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. A request missing either header, or presenting a role string the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not listed among the roles permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system declares exactly six roles, spelled precisely as follows:

- `PlanAdmin` — health plan platform administrator; owns reference data, go-live approval, termination finalization, and the logical clock.
- `ContractManager` — provider contracting negotiator; owns contract drafting, the negotiation cycle, versions and amendments, termination notices, and continuity-of-care cases.
- `ContractLegal` — contract language counsel; signs contracts (segregated from the submitter) and owns carve-outs.
- `ConfigurationAnalyst` — fee schedule configuration and claims testing analyst; owns version load and validation, fee schedule entries, and simulation batches.
- `PaymentIntegrityAnalyst` — payment integrity analyst; owns paid-claim ledger loads and retro adjustment adjudication.
- `ProviderRep` — provider representative with read-only access scoped to their own organization's contract chain.

For `PlanAdmin`, `ContractManager`, `ContractLegal`, `ConfigurationAnalyst`, and `PaymentIntegrityAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `submitted_by_user_id` or `signed_by_user_id` on a contract, or as `actor_id` on an audit event — but it is never compared to any entity's `id`.

When `X-User-Role` is `ProviderRep`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare the resource's provider chain to `X-User-ID`. The provider chain is resolved as follows: for a provider resource, its own `id`; for a contract, its `provider_id`; for a contract version or fee schedule entry, the `provider_id` of the owning contract reached through the version. The ownership check applies to exactly eight read endpoints: `GET /providers/{id}`, `GET /providers/{id}/contracts`, `GET /contracts/{id}`, `GET /contracts/{id}/versions`, `GET /contract-versions/{id}`, `GET /contract-versions/{id}/fee-schedule-entries`, `GET /fee-schedule-entries/{id}`, and `GET /contracts/{id}/audit-events`. On those eight, a `ProviderRep` whose `X-User-ID` does not match the resource's provider chain is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). Reference-data reads (networks, Medicare benchmarks, rate parity rules) are open to all six roles without an ownership comparison.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Contract Audit Trail

Every resource exposed by this API carries a standard set of system-managed properties alongside its business fields:

- `id` (string): a server-minted UUID with no type prefix, unique across the resource's collection.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation of the resource and underpins optimistic concurrency control where §2.7 applies.

One resource is the exception. An audit event is immutable once appended, so it carries only `id` and `created_at`; `updated_at` and `version` are absent from it by design.

Every material event in a contract's lifetime appends an audit event to that contract's log. Each event records the owning `contract_id`, a machine-readable `event_type` (for example `CONTRACT_SIGNED`, `VERSION_EFFECTIVE`, or `NOTICE_ISSUED`), the acting `actor_role` taken from the caller's `X-User-Role`, the `actor_id` taken from the caller's `X-User-ID` (or the literal value `system` when a cascade or automatic transition fires the event), a human-readable `detail` string, and `occurred_at`, which is stamped from the logical clock described in §2.6 rather than from wall-clock time. The log is strictly append-only: events are never edited or deleted. The trail is read through the contract's audit collection or, for a single event, by event id; an event id that does not resolve fails with `ERR_AUDIT_EVENT_NOT_FOUND`.

### 2.5. Monetary Precision, Basis Points, and Rounding Order

All amounts of money in this API are integer cents. No field ever carries a fractional cent, and all arithmetic that would produce one resolves it immediately.

Rates, escalators, parity bands, and thresholds are expressed in basis points with a fixed denominator of ten thousand: an escalator of 300 basis points is a 3.00% annual uplift, a parity band of 11,000 basis points permits a rate ratio of at most 110.00%, and the regulatory floor of 8,000 basis points is 80.00% of the Medicare benchmark.

Wherever a multiplication or division would yield a fractional cent, the result is rounded half up to the nearest whole cent. Two rounding-order rules are pinned and may not be reordered. First, every claim line is rounded to whole cents on its own, and batch totals are produced by summing the already-rounded line values; summing unrounded values and rounding the total is never used. Second, annual escalator compounding applies each completed step to the whole-cent result of the previous step, so the escalator never compounds on fractional cents. One further integer rule belongs to go-live: the cross-product rate ratio used by rate parity evaluation is computed with integer division that discards the fractional remainder, as detailed in §3.7.

### 2.6. Effective Dating, Window Semantics, and the Logical Clock

Three distinct window conventions coexist in this domain, and confusing them is the classic implementation defect in contracting systems.

Contract versions govern **half-open** service-date windows: a version's rates apply to service dates on or after its `effective_date` and before the effective date of the version that supersedes it. Consequently two versions of the same contract may never share an `effective_date` — equal starts collide — while any two distinct effective dates, however close, never conflict.

Carve-out windows are **closed** intervals: both `start_date` and `end_date` are inclusive, and two windows on the same version for the same service category conflict not only when they truly overlap but also when they are merely adjacent, with one window ending the day before the other begins (§3.5). Retro adjustment runs sweep a **half-open** window: service dates on or after `window_start_date` and strictly before `window_end_date` (§3.8). Continuity-of-care coverage ends on a computed `coverage_end_date`, itself a closed boundary (§3.9).

Time itself is governed by a logical clock, not the wall clock. Before any clock-setting call, the logical current instant defaults to 2026-05-01T00:00:00Z. A `PlanAdmin`-only capability, `POST /_clock/set_current_utc`, advances the logical clock to a supplied `to_iso8601` instant; once set, the clock never falls back to wall-clock time. The logical clock gates termination finalization and continuity-case expiry (§3.9) and stamps every audit event's `occurred_at`.

### 2.7. Optimistic Concurrency Control on Amendment and Notice Creation

Two creation operations participate in optimistic concurrency control against the contract aggregate, and both name their guard field `expected_contract_version`: creating an amendment version under a contract, and drafting a termination notice on a contract. On both, the field is non-optional and carries the value of the contract's `version` counter that the client last observed.

If the contract's current `version` has advanced beyond the carried value — because any contract-mutating operation completed after the client's last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is created. This is purely a stale-read guard: it compares the carried value to the contract's current `version` at the moment the write is evaluated. The guard exists because uniqueness rules cannot substitute for it — several draft versions, or several draft notices, may legitimately coexist on one contract, so the only correct rejection signal for a client acting on an outdated view of the amendment or notice set is the version comparison. No endpoint other than these two accepts a version field; every other write is protected by its state preconditions alone.

### 2.8. Cascading State Propagation Across the Contract Aggregate

A single request in this system frequently moves more than one resource. The cascade doctrine is uniform: the primary transition and all of its linked secondary transitions commit atomically within the triggering request, each secondary transition is conditional on the target's current state, and every cascade appends its own audit events to the parent contract's log.

The cascades are: go-live activation (the contract's move to `ACTIVE` drives its validated version to `EFFECTIVE`, which in turn supersedes any previously effective version and may spawn a retro adjustment run — §3.7); version validation (a version becoming `VALIDATED` locks every mapped fee schedule entry — §3.4); notice issuance (a notice becoming `ISSUED` moves its contract from `ACTIVE` to `TERMINATION_NOTICE` — §3.9); notice finalization (the notice becoming `EFFECTIVE` terminates the contract, conditionally activates notified continuity cases, and conditionally closes non-terminal simulation batches — §3.9); notice rescission (a compensating cascade that returns the contract to `ACTIVE` and closes pre-coverage continuity cases — §3.9); batch reopen (a compensating reset of all resolved simulation claims to pending — §3.6); run void (a compensating voiding of all proposed adjustments with run totals returned to zero — §3.8); and the settlement bubble-up (a finalized run that advances itself to `SETTLED` once no adjustment remains in a non-terminal state — §3.8).

Mutations refresh `updated_at` on the affected resource and increment `version` only where the workflow sections say so. In particular, every contract lifecycle transition increments the contract's `version` by one, and so do amendment-version creation and termination-notice creation; cascades into child resources do not bump the parent contract's `version` beyond what the triggering transition specifies, and an audit-event append on its own never bumps anything.

### 2.9. Nested Resource Retrieval and Existence Failures

The API enforces strict, hierarchical, left-to-right validation on every path that contains resource identifiers. Each identifier in the path is resolved in sequence, and the request is rejected immediately with the not-found error belonging to the first identifier that fails to resolve; later segments are never consulted. A request to map a benchmark under a contract version that does not exist therefore fails with `ERR_VERSION_NOT_FOUND` before the entry is ever examined, and a claim added to a nonexistent batch fails with `ERR_BATCH_NOT_FOUND`.

The existence family maps one error to each addressable resource: `ERR_PROVIDER_NOT_FOUND` for providers, `ERR_NETWORK_NOT_FOUND` for networks (whether the network id arrives in the path or in the request body), `ERR_BENCHMARK_NOT_FOUND` for Medicare benchmarks, `ERR_PARITY_RULE_NOT_FOUND` for rate parity rules, `ERR_CONTRACT_NOT_FOUND` for contracts, `ERR_VERSION_NOT_FOUND` for contract versions, `ERR_ENTRY_NOT_FOUND` for fee schedule entries, `ERR_CARVE_OUT_NOT_FOUND` for carve-outs, `ERR_BATCH_NOT_FOUND` for simulation batches, `ERR_PAID_CLAIM_NOT_FOUND` for paid claim snapshots, `ERR_RUN_NOT_FOUND` for retro adjustment runs, `ERR_ADJUSTMENT_NOT_FOUND` for retro adjustments, `ERR_NOTICE_NOT_FOUND` for termination notices, `ERR_CASE_NOT_FOUND` for continuity-of-care cases, and `ERR_AUDIT_EVENT_NOT_FOUND` for audit events. All fifteen carry HTTP 404. Existence is evaluated only after authentication, role authorization, and provider-ownership scoping, and before any state precondition or business rule.

### 2.10. Validation Evaluation Order

When a request fails several rules at once, the error it receives is determined by a fixed evaluation order, not by whichever check happens to run first. The tiers, evaluated in this sequence, are:

1. **Request conformance** — the body must conform to the endpoint's input schema: required fields present, types valid, enum values within their declared sets, and no undeclared fields. Violations yield `ERR_INVALID_REQUEST` (HTTP 400). This tier also governs conditionally required fields, such as a percentage on a percent-of-Medicare entry.
2. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and the role declared, else `ERR_UNAUTHENTICATED` (HTTP 401).
3. **Role authorization** — the role must appear in the endpoint's authorized list, else `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
4. **Provider ownership scoping** — on the eight reads enumerated in §2.1, a `ProviderRep`'s chain must match, else `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).
5. **Existence** — every path identifier resolves left-to-right per §2.9, producing the appropriate 404.
6. **State preconditions and optimistic concurrency** — the target resources must be in states that permit the requested transition, and on the two guarded creations the `expected_contract_version` must match. Violations produce the relevant 409 invalid-state error or `ERR_STALE_VERSION` (HTTP 412).
7. **Business safety** — the regulatory rate floor (`ERR_RATE_BELOW_FLOOR`), segregation of duties at signature (`ERR_SEGREGATION_OF_DUTIES`), and the continuity-of-care treatment window (`ERR_COC_WINDOW_EXCEEDED`).
8. **Temporal rules** — notice period sufficiency (`ERR_NOTICE_PERIOD_INSUFFICIENT`), version effective-window collision (`ERR_VERSION_WINDOW_OVERLAP`), carve-out window conflict (`ERR_CARVE_OUT_WINDOW_CONFLICT`), and retro-window validity (`ERR_RETRO_WINDOW_INVALID`).
9. **Uniqueness and batch population** — duplicate benchmark (`ERR_DUPLICATE_BENCHMARK`), duplicate version number (`ERR_DUPLICATE_VERSION_NUMBER`), duplicate service code (`ERR_DUPLICATE_SERVICE_CODE`), duplicate claim number (`ERR_DUPLICATE_CLAIM_NUMBER`), and the non-empty-batch gate on scoring (`ERR_BATCH_EMPTY`).
10. **Referential business rules** — benchmark resolvable at entry creation (`ERR_BENCHMARK_UNRESOLVABLE`), benchmark published at mapping time (`ERR_BENCHMARK_UNPUBLISHED`), referenced network active (`ERR_NETWORK_INACTIVE`), and a validated version present for testing entry (`ERR_NO_VALIDATED_VERSION`).
11. **Fiscal gates** — rate parity at go-live (`ERR_RATE_PARITY_VIOLATION`) and the simulation pass requirement behind readiness (`ERR_SIMULATION_THRESHOLD_NOT_MET`).

An endpoint that carries several checks within one tier applies them in the order its workflow narrative in §3 states; where the relative order matters for which error surfaces, §3 calls the sequence out explicitly.

## 3. Business Logic & Workflows

### 3.1. Reference Data Governance: Networks, Medicare Benchmarks, and Parity Rules

A `PlanAdmin` begins by establishing the reference data every downstream contract depends on. A **network** is created with a display `name` and a `line_of_business` drawn from exactly four values: `COMMERCIAL_HMO`, `COMMERCIAL_PPO`, `MEDICARE_ADVANTAGE`, or `MEDICAID`. Its `network_status` begins as `ACTIVE`. Retirement moves a network from `ACTIVE` to `RETIRED`, increments the network's `version` by one, and forecloses new contract creation against it (§3.2); existing contracts are untouched. The network collection can be listed with an optional `line_of_business` filter, and a network's roster of participating contracts is readable by every internal role. A network id that does not resolve — whether carried in the path or in a request body — fails with `ERR_NETWORK_NOT_FOUND`.

**Medicare benchmarks** are the pricing backbone. A `PlanAdmin` loads each row with a `benchmark_year`, a `locality_code`, an `hcpcs_code`, and a `benchmark_amount_cents`. The triple of year, locality, and code is unique across the dataset: loading a second row for an existing triple is rejected with `ERR_DUPLICATE_BENCHMARK` (HTTP 409). Every row begins its life with `benchmark_status` set to `DRAFT`, and draft rows are inert — they are never eligible for benchmark resolution at map time. Publishing, again a `PlanAdmin` action, moves a row from `DRAFT` to `PUBLISHED` and increments its `version` by one; attempting to publish a row that is no longer `DRAFT` is rejected with `ERR_BENCHMARK_INVALID_STATE` (HTTP 409), and an unresolvable benchmark id draws `ERR_BENCHMARK_NOT_FOUND`. The benchmark list supports optional filters on `benchmark_year`, `hcpcs_code`, and `locality_code`.

**Rate parity rules** encode how far apart the same provider's rates may drift across two lines of business. A `PlanAdmin` authors a rule with `line_of_business_a`, `line_of_business_b`, and `band_bps` — the maximum permitted ratio of the higher escalator-projected rate to the lower, expressed in basis points, so a band of 11,000 basis points permits the higher rate to reach at most 110.00% of the lower. The two lines of business must differ from one another, and at most one `ACTIVE` rule may exist for an unordered pair of lines of business: a rule naming commercial HMO against Medicaid is the same rule as one naming Medicaid against commercial HMO. A rule's `rule_status` begins as `ACTIVE` (the enumeration also admits `RETIRED`). Parity rules are inert configuration until go-live, where §3.7 gives them teeth; an unknown rule id fails with `ERR_PARITY_RULE_NOT_FOUND`.

### 3.2. Provider Onboarding and Contract Drafting

Before any contracting can occur, a `PlanAdmin` registers the **provider** with its `legal_name`, `tin`, `npi`, and `locality_code`. The tax identification number and national provider identifier are each unique across all providers — a duplicate is rejected at creation. The locality code matters far beyond the directory: it is the geographic key through which every fee schedule entry later resolves its Medicare benchmark. The provider record carries a `provider_status` that begins as `ACTIVE`; the enumeration also admits `SUSPENDED`. The provider list is paginated via `limit` and `offset` and accepts an optional `locality_code` filter. A provider id that does not resolve fails with `ERR_PROVIDER_NOT_FOUND`.

A `ContractManager` drafts a **contract** under a provider by supplying the `network_id` of the product network the contract participates in, the `base_effective_date` anchoring the agreement, a `term_months` initial term, an `escalator_bps` annual rate escalator in basis points, an `escalator_mode` of either `ANNIVERSARY` or `CALENDAR`, and an optional `auto_renew` flag that defaults to false. Creation applies its checks in order: the path provider must resolve (`ERR_PROVIDER_NOT_FOUND`), the referenced network must resolve (`ERR_NETWORK_NOT_FOUND`), and only then is the network required to still be `ACTIVE`, failing with `ERR_NETWORK_INACTIVE` (HTTP 422) otherwise. A new contract begins with `contract_status` set to `DRAFT` and `negotiation_round` at zero, and its creation appends a `CONTRACT_CREATED` event to its own audit trail. From this point forward, any contract id that fails to resolve — on any contract-scoped endpoint — produces `ERR_CONTRACT_NOT_FOUND`.

### 3.3. The Negotiation Cycle and Segregated Signature

Negotiation opens when a `ContractManager` begins negotiation on a draft contract, moving `contract_status` from `DRAFT` to `IN_NEGOTIATION`, incrementing the contract's `version` by one, and appending `CONTRACT_NEGOTIATION_STARTED`. Every lifecycle action described in this section — and every later one — first requires the contract to be in the state that permits it; a mismatched state is rejected with `ERR_CONTRACT_INVALID_STATE` (HTTP 409).

When terms are settled internally, the `ContractManager` submits the contract for signature: `IN_NEGOTIATION` becomes `PENDING_SIGNATURE`, the caller's `X-User-ID` is captured into `submitted_by_user_id`, the `version` increments, and `CONTRACT_SUBMITTED_FOR_SIGNATURE` is appended. A counter-offer returns the contract from `PENDING_SIGNATURE` to `IN_NEGOTIATION`: `negotiation_round` increments by one (it accumulates across as many submit-counter-resubmit cycles as the negotiation requires), `submitted_by_user_id` is cleared to null, an optional `note` may accompany the counter-offer, the `version` increments, and `CONTRACT_COUNTER_OFFER` is appended.

Signature belongs to `ContractLegal` alone, and the two signature-time checks run in a fixed order: the contract must first be in `PENDING_SIGNATURE` (`ERR_CONTRACT_INVALID_STATE` otherwise), and only then is segregation of duties evaluated — the signing caller's `X-User-ID` must differ from the contract's recorded `submitted_by_user_id`, so the negotiator who submitted the terms can never be the counsel who signs them. A same-identity signature is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). A clean signature moves the contract from `PENDING_SIGNATURE` to `SIGNED`, records the signer in `signed_by_user_id`, increments the `version`, and appends `CONTRACT_SIGNED`.

### 3.4. Amendment Versions, Fee Schedule Construction, and Benchmark Mapping

Rates never attach to a contract directly; they attach to a **contract version**, the amendment unit. A `ContractManager` creates a version under a contract by supplying a `version_number`, an `effective_date`, an optional `retro_effective_date`, and the concurrency guard `expected_contract_version` described in §2.7. Creation enforces its checks in order: the contract must resolve (`ERR_CONTRACT_NOT_FOUND`); the stale-version guard rejects an outdated view of the contract with `ERR_STALE_VERSION` (HTTP 412); the temporal checks follow — the `effective_date` must differ from every other version's `effective_date` on the same contract, because half-open windows with equal starts overlap, failing with `ERR_VERSION_WINDOW_OVERLAP` (HTTP 409), and a `retro_effective_date`, when present, must fall on or after the contract's `base_effective_date` and strictly before the version's own `effective_date`, failing with `ERR_RETRO_WINDOW_INVALID` (HTTP 422); finally a `version_number` already used on the contract is rejected with `ERR_DUPLICATE_VERSION_NUMBER` (HTTP 409). A successfully created version begins with `version_status` set to `DRAFT`, increments the parent contract's `version` by one, and appends `VERSION_CREATED` to the contract's audit trail. An unresolvable version id anywhere downstream fails with `ERR_VERSION_NOT_FOUND`.

A `ConfigurationAnalyst` builds the version's fee schedule entry by entry. Entry creation is permitted only while the version is in `DRAFT`, `LOADED`, or `REJECTED`; against any other version state it fails with `ERR_VERSION_INVALID_STATE` (HTTP 409). Each entry carries an `hcpcs_code` that is unique within its version, a free-form `service_category` label (values such as OFFICE_VISIT or INPATIENT_SURGERY) used later for carve-out matching, a `rate_type` of `PERCENT_OF_MEDICARE`, `FLAT_RATE`, `PER_DIEM`, or `CASE_RATE`, and the rate payload matching that type: `pct_of_medicare_bps` is required for percent-of-Medicare entries, while `flat_rate_cents` is required for the other three types, where it serves as the flat amount, the per-day base, or the case base respectively. An optional `benchmark_lookup_mode` of `STRICT` or `PROVISIONAL` defaults to `STRICT`. Freshly created entries are `STAGED` (their `entry_status`), with `medicare_benchmark_id`, `resolved_benchmark_cents`, and `computed_rate_cents` all unset — each is null until mapping. Entry creation sequences its checks: the version resolves, the version state permits child creation, the regulatory floor then requires a percent-of-Medicare entry's `pct_of_medicare_bps` to be at least 8,000 basis points — 80.00% of the Medicare benchmark — with violations rejected as `ERR_RATE_BELOW_FLOOR` (HTTP 422), a duplicate `hcpcs_code` on the version draws `ERR_DUPLICATE_SERVICE_CODE` (HTTP 409), and last, for percent-of-Medicare entries only, at least one Medicare benchmark row of any status must exist for the entry's code and the provider's locality, failing with `ERR_BENCHMARK_UNRESOLVABLE` (HTTP 422) when none does. An entry id that fails to resolve draws `ERR_ENTRY_NOT_FOUND`. Entries are listable per version, or across versions through a filtered collection accepting `contract_version_id` and `medicare_benchmark_id` query parameters.

The load-and-validate cycle moves a version toward usability. Loading takes a version from `DRAFT` to `LOADED` and appends `VERSION_LOADED` to the contract's audit trail. Validation of a `LOADED` version has exactly two sibling outcomes, both recorded: when at least one entry exists and every entry has reached `MAPPED`, the version becomes `VALIDATED`, every mapped entry cascades from `MAPPED` to `LOCKED`, and `VERSION_VALIDATED` is appended; when the version holds zero entries or any entry is still `STAGED`, the version becomes `REJECTED` and `VERSION_REJECTED` is appended. A rejected version is not dead: loading it again returns it from `REJECTED` to `DRAFT` for correction (appending `VERSION_RELOADED`), from which a further load returns it to `LOADED`.

**Benchmark mapping** is the act that prices an entry. A `ConfigurationAnalyst` maps an entry whose `entry_status` is `STAGED` — any other entry state fails with `ERR_ENTRY_INVALID_STATE` (HTTP 409) — and whose parent version remains in `DRAFT`, `LOADED`, or `REJECTED`. Resolution first assembles the candidate set: Medicare benchmark rows whose `hcpcs_code` equals the entry's code, whose `locality_code` equals the provider's locality (reached through the version's contract), and whose `benchmark_status` is `PUBLISHED`; draft benchmarks never enter the set. The two lookup modes then diverge. Under `STRICT`, only rows whose `benchmark_year` equals the calendar year of the version's `effective_date` survive — an unpublished year is an error, never a fallback. Under `PROVISIONAL`, rows whose `benchmark_year` is no later than the effective year survive, ranked by year descending with the most recent taken; the composite uniqueness of year, locality, and code makes ties impossible, and no id-based tiebreak is ever used. An empty candidate set — under either mode — is rejected with `ERR_BENCHMARK_UNPUBLISHED` (HTTP 422). A successful mapping stamps `medicare_benchmark_id` and `resolved_benchmark_cents` from the resolved row and computes the entry's `computed_rate_cents`: for percent-of-Medicare entries, the resolved benchmark cents multiplied by `pct_of_medicare_bps` and divided by ten thousand, rounded half up to whole cents; for flat-rate, per-diem, and case-rate entries, the entry's own `flat_rate_cents` stands as the base, since length-of-stay multiplication and case outlier adjustments are applied per claim, never at mapping. The entry advances from `STAGED` to `MAPPED`.

**Escalator projection** converts a mapped base rate into the rate in force on any given service date, and it is consulted by both simulation pricing (§3.6) and retro repricing (§3.8). The step count depends on the contract's `escalator_mode`. Under `ANNIVERSARY`, the count is the number of completed anniversaries of the version's `effective_date` that fall on or before the service date. Under `CALENDAR`, the count is the service date's calendar year minus the effective date's calendar year. Either way the count never falls below zero. Each step multiplies the running whole-cent amount by one plus the escalator fraction — the contract's `escalator_bps` divided by ten thousand — and the result of each step is rounded half up to whole cents before the next step applies; zero steps leave the base rate unchanged. The modes genuinely diverge: for a version effective 2026-07-01 and a service date of 2027-06-15, `ANNIVERSARY` counts zero steps (the first anniversary, 2027-07-01, has not yet arrived) while `CALENDAR` counts one, so identical contract data prices the same claim differently under the two modes.

### 3.5. Contract Language Exceptions: Carve-Out Windows and Overrides

Contract language routinely excepts specific service categories from the fee schedule, and a `ContractLegal` author records each exception as a **carve-out** on a version. Like entries, carve-outs are accepted only while the version is in `DRAFT`, `LOADED`, or `REJECTED`; otherwise creation fails with `ERR_VERSION_INVALID_STATE`. Each carve-out names a `service_category` — where the literal value `"*"` acts as a wildcard matching any claim's category at pricing time, though window-conflict checks compare the literal value only, so a `"*"` carve-out and an OFFICE_VISIT carve-out never conflict on category grounds — an `override_type` of `FLAT_RATE`, `PCT_OF_MEDICARE`, or `EXCLUDE`, the matching payload (`override_flat_cents` is required for a flat-rate override, `override_pct_bps` for a percent-of-Medicare override, and an exclusion carries neither — supplying either override payload field on an exclusion is a request-conformance violation, rejected with `ERR_INVALID_REQUEST` (HTTP 400)), a `start_date` and `end_date` delimiting a closed, inclusive window, and a `priority_rank` under which a lower number wins when several carve-outs match the same claim, with ties broken by earlier `created_at`.

Window discipline on carve-outs is deliberately stricter than on versions. Against every existing carve-out of the same version bearing the same literal `service_category`, a new window conflicts — and is rejected with `ERR_CARVE_OUT_WINDOW_CONFLICT` (HTTP 409) — when the new window's `start_date` falls on or before the day after the existing window's `end_date` and the existing window's `start_date` falls on or before the day after the new window's `end_date`. True overlaps and back-to-back adjacency (one window ending the day before the other begins) are therefore both rejected, in deliberate contrast to version effective windows, where distinct dates never conflict. A carve-out id that fails to resolve draws `ERR_CARVE_OUT_NOT_FOUND`.

### 3.6. Configuration Testing: Simulation Batches, Claim Pricing, and Scoring

A signed contract enters build-out when a `ConfigurationAnalyst` begins configuration, moving `contract_status` from `SIGNED` to `IN_CONFIGURATION`, incrementing the `version`, and appending `CONTRACT_CONFIGURATION_STARTED`. Testing begins only when there is something worth testing: beginning testing requires the contract to be in `IN_CONFIGURATION` (`ERR_CONTRACT_INVALID_STATE` otherwise) and at least one of its versions to have reached `VALIDATED`, failing with `ERR_NO_VALIDATED_VERSION` (HTTP 422) when none has. Success moves the contract to `IN_TESTING`, increments the `version`, and appends `CONTRACT_TESTING_STARTED`. Should testing expose configuration defects, returning to configuration moves the contract from `IN_TESTING` back to `IN_CONFIGURATION`, again incrementing the `version` and appending `CONTRACT_RETURNED_TO_CONFIGURATION`.

Within a `VALIDATED` or `EFFECTIVE` version — batch creation against any other version state fails with `ERR_VERSION_INVALID_STATE` — a `ConfigurationAnalyst` opens a **simulation batch** with a human-readable `label`. A new batch begins with `batch_status` set to `OPEN` and every counter at zero: `total_claims`, `matched_claims`, `mismatched_claims`, `excluded_claims`, `pending_claims`, and `total_priced_cents`. A batch id that fails to resolve draws `ERR_BATCH_NOT_FOUND`.

Test claims accumulate while the batch is `OPEN`; adding a claim to a batch in any other state fails with `ERR_BATCH_INVALID_STATE` (HTTP 409). Each claim, bound to its batch through `simulation_batch_id`, carries an `hcpcs_code`, a `service_category`, a `service_date`, a `billed_cents` charge, the tester's `expected_allowed_cents`, and an optional `los_days` length of stay that defaults to 1 and is consulted only by per-diem pricing. A claim's `claim_outcome` begins as `PENDING` with `priced_allowed_cents` null, and every claim added recomputes the batch's `total_claims` and `pending_claims`, each rising by one.

Pricing the batch — permitted only from `OPEN` — prices every pending claim through a fixed four-step pipeline and moves the batch from `OPEN` to `PRICED`. Step one is carve-out override selection: the candidates are the version's carve-outs whose `service_category` equals the claim's category or is the wildcard `"*"`, and whose closed window covers the claim's `service_date`; candidates rank by `priority_rank` ascending with ties broken by earlier `created_at`, and the first is taken. An `EXCLUDE` selection ends the line immediately: the claim becomes `EXCLUDED` and its `priced_allowed_cents` stays null. A `FLAT_RATE` selection sets the line's allowed amount to `override_flat_cents` and proceeds to rounding. A `PCT_OF_MEDICARE` selection sets it to the entry's `resolved_benchmark_cents` multiplied by `override_pct_bps` and divided by ten thousand, rounded half up, and proceeds to rounding. Step two, entry pricing, runs only when no carve-out matched: the version's entry bearing the claim's `hcpcs_code` is located (unique per version), and if none exists the claim becomes `MISMATCH` with `priced_allowed_cents` null. Otherwise the escalator-projected base rate at the claim's `service_date` is computed per §3.4. Percent-of-Medicare and flat-rate entries take the projected base as the line amount; per-diem entries multiply the projected base by the claim's `los_days`. Case-rate entries run the outlier branch: when the billed charge multiplied by ten thousand strictly exceeds thirty thousand times the base — an exact integer comparison in which a billed charge of exactly three times the base does not qualify — the excess is the billed charge minus the threshold amount (the threshold being thirty thousand basis points of the base, rounded half up to whole cents), and the line amount becomes the base plus 80.00% of that excess, the share itself rounded half up to whole cents; when the threshold is not crossed, the base stands; and in both sub-cases the result is capped at the billed charge, the lesser of the two amounts prevailing. Step three pins the rounding order: each claim line is rounded half up to whole cents first, and the batch's `total_priced_cents` is the sum of the already-rounded `priced_allowed_cents` values over claims whose outcome is `MATCH` or `MISMATCH`; summing first and rounding once is never used. Step four assigns the outcome: a line amount exactly equal to `expected_allowed_cents` yields `MATCH`, anything else yields `MISMATCH`. After the sweep the batch's counters — matched, mismatched, excluded, pending, and total priced — are recomputed in full.

Scoring turns a priced batch into a verdict and is permitted only from `PRICED` (any other state draws `ERR_BATCH_INVALID_STATE`). The batch must contain at least one claim in total, failing with `ERR_BATCH_EMPTY` (HTTP 422) when empty. The priced population counts matched plus mismatched claims only — excluded and pending claims never enter either side of the comparison. The batch passes when `matched_claims` multiplied by ten thousand is at least the priced population multiplied by 7,500 basis points (75.00%): an exact integer comparison with no division and no rounding, under which a match share exactly equal to the threshold passes. A passing batch moves from `PRICED` to `PASSED` and appends `SIMULATION_PASSED` to the contract's audit trail; a failing batch moves to `FAILED` and appends `SIMULATION_FAILED`.

A failed batch is reworkable. Reopening — permitted only from `FAILED` — returns the batch to `OPEN` and compensates in full: every claim whose outcome was `MATCH`, `MISMATCH`, or `EXCLUDED` reverts to `PENDING` with its `priced_allowed_cents` reset to null, the matched, mismatched, and excluded counters return to zero, `pending_claims` is restored to `total_claims`, and `total_priced_cents` returns to zero. The claims themselves are never deleted by a reopen.

### 3.7. Go-Live Approval, Rate Parity Enforcement, and Activation

Readiness is asserted by a `ConfigurationAnalyst` marking the contract ready. The contract must be `IN_TESTING` (`ERR_CONTRACT_INVALID_STATE` otherwise), and at least one `PASSED` simulation batch must exist beneath a `VALIDATED` version of the contract — its absence fails with `ERR_SIMULATION_THRESHOLD_NOT_MET` (HTTP 422). A successful assertion moves the contract from `IN_TESTING` to `READY_FOR_GO_LIVE`, increments the `version`, and appends `CONTRACT_READY_FOR_GO_LIVE`.

Go-live itself belongs to `PlanAdmin` and carries the system's signature fiscal gate. The contract must stand `READY_FOR_GO_LIVE` (`ERR_CONTRACT_INVALID_STATE` otherwise), after which rate parity evaluation runs to completion before any activation occurs. Let the activating contract's provider and its network's line of business frame the check: for every `ACTIVE` parity rule whose line-of-business pair contains the activating contract's line of business, the evaluation gathers that provider's other `ACTIVE` contracts participating in the paired line of business. For each such contract holding an `EFFECTIVE` version, every `hcpcs_code` present as a `LOCKED` entry in both that version and the activating version contributes a ratio: both entries' rates are escalator-projected at the activating version's `effective_date`, the greater projected rate is multiplied by ten thousand and divided by the lesser using integer division that discards the fractional remainder, and the resulting quotient is compared to the rule's `band_bps`. A quotient strictly greater than the band rejects the entire go-live with `ERR_RATE_PARITY_VIOLATION` (HTTP 422); a quotient exactly equal to the band passes. When no parity rule matches the line of business, no other `ACTIVE` contract exists on the paired side, or no procedure code overlaps, the check passes vacuously.

An approved go-live fires the deepest cascade in the system. The contract moves from `READY_FOR_GO_LIVE` to `ACTIVE` and its `version` increments; its `VALIDATED` version cascades from `VALIDATED` to `EFFECTIVE`, appending `VERSION_EFFECTIVE`; any previously `EFFECTIVE` version of the same contract cascades from `EFFECTIVE` to `SUPERSEDED`, appending `VERSION_SUPERSEDED`; and when the newly effective version carries a `retro_effective_date` earlier than its own `effective_date`, a retro adjustment run is spawned under that version in `CREATED` state (its `run_status`), with `window_start_date` set to the retro date and `window_end_date` set to the effective date. `CONTRACT_GO_LIVE` closes the event sequence on the contract's audit trail.

Activation is not a one-way door for amendments. An `ACTIVE` contract may re-enter configuration through the same begin-configuration action, moving from `ACTIVE` to `IN_CONFIGURATION`, incrementing the `version`, and appending `CONTRACT_AMENDMENT_CONFIGURATION_STARTED`. The amendment then walks the same gauntlet as the original build — `IN_CONFIGURATION` to `IN_TESTING` to `READY_FOR_GO_LIVE` to `ACTIVE` — and each subsequent activation supersedes the version that was effective before it.

### 3.8. The Paid-Claim Ledger and Retroactive Adjustment Settlement

Once a contract is `ACTIVE`, a `PaymentIntegrityAnalyst` loads its paid-claim ledger. Loading against a contract in any other state fails with `ERR_CONTRACT_INVALID_STATE`. Each **paid claim snapshot** records an external `claim_number` — unique per contract, duplicates rejected with `ERR_DUPLICATE_CLAIM_NUMBER` (HTTP 409) — along with the `hcpcs_code`, `service_category`, `service_date`, `billed_cents`, and the `paid_cents` originally disbursed. Snapshots begin with `snapshot_status` set to `OPEN`. A snapshot id that fails to resolve draws `ERR_PAID_CLAIM_NOT_FOUND`.

A retro adjustment run spawned at go-live (§3.7) begins with its `run_status` at `CREATED` and all four totals at zero. Computing it — permitted only from `CREATED`, otherwise `ERR_RUN_INVALID_STATE` (HTTP 409) — sweeps the contract's snapshots: candidates are those still `OPEN` whose `service_date` falls inside the run's half-open window, on or after `window_start_date` and strictly before `window_end_date`; snapshots already `ADJUSTED` and out-of-window dates are excluded. The sweep processes candidates oldest service date first, breaking ties by earlier `created_at` and never by id. Each candidate reprices under the run's version: the version's entry bearing the snapshot's `hcpcs_code` must exist and be `LOCKED`; carve-out override selection runs exactly as simulation pricing runs it, with one deliberate difference — an `EXCLUDE` selection does not exclude the snapshot, which is instead priced at its escalator-projected entry rate. The resulting `repriced_allowed_cents` is the override amount when a non-excluding carve-out matches and the projected entry rate otherwise. The signed `delta_cents` is the repriced amount minus the originally paid amount: a positive delta creates an adjustment with `direction` `UNDERPAID`, a negative delta one with `direction` `OVERPAID`, and a delta of exactly zero creates no row at all. Every created adjustment begins with `adjustment_status` at `PROPOSED` and copies its `service_date` and `original_paid_cents` from the snapshot it references, naming that snapshot through `paid_claim_id` and its owning run through `retro_run_id`. Compute never mutates the snapshots themselves. After the sweep, the run's totals are recomputed over its non-`VOIDED` adjustments: `total_underpaid_cents` sums the positive deltas, `total_overpaid_cents` sums the magnitudes of the negative deltas, `net_delta_cents` is the underpaid total minus the overpaid total, and `adjustment_count` counts the rows. The run stands `COMPUTED`. A run id that fails to resolve draws `ERR_RUN_NOT_FOUND`, an adjustment id draws `ERR_ADJUSTMENT_NOT_FOUND`, and the adjustment collection can also be listed filtered by `paid_claim_id`.

Finalizing a computed run — again only from `COMPUTED`, else `ERR_RUN_INVALID_STATE` — commits the sweep to the ledger: every snapshot referenced by a `PROPOSED` adjustment of the run moves from `OPEN` to `ADJUSTED`, the run becomes `FINALIZED`, and `RETRO_RUN_FINALIZED` is appended to the contract's audit trail. Voiding is the compensating path from the same state: the run becomes `VOID`, every `PROPOSED` adjustment of the run cascades to `VOIDED`, all four run totals reset to zero, the snapshots remain `OPEN` (compute never touched them), and the paid ledger emerges unchanged end-to-end, with `RETRO_RUN_VOIDED` appended.

Adjudication then proceeds adjustment by adjustment under the `PaymentIntegrityAnalyst`. Approving moves a `PROPOSED` adjustment to `APPROVED`; rejecting moves it to `REJECTED`; both require the parent run to be `COMPUTED` or `FINALIZED`, and any other combination of adjustment and run state fails with `ERR_ADJUSTMENT_INVALID_STATE` (HTTP 409). Settling an `APPROVED` adjustment pays by direction: an `UNDERPAID` adjustment settles to `PAID`, an `OVERPAID` one to `RECOVERED`, and any mismatch between direction and the settled target is likewise `ERR_ADJUSTMENT_INVALID_STATE`. The run watches its children: while the run is `FINALIZED`, the moment no adjustment remains in `PROPOSED` or `APPROVED` — the last non-terminal adjustment having just settled or been rejected — the run advances itself from `FINALIZED` to `SETTLED` and appends `RETRO_RUN_SETTLED`. A run still `COMPUTED` whose adjustments all happen to resolve does not settle; only finalization arms the bubble-up. `SETTLED` and `VOID` are the run's terminal states, and `PAID`, `RECOVERED`, `REJECTED`, and `VOIDED` are an adjustment's.

### 3.9. Termination, Rescission, and Continuity-of-Care Obligations

Termination begins on paper. A `ContractManager` drafts a **termination notice** against an `ACTIVE` contract, supplying the `notice_date`, the `termination_date`, a free-text `reason`, and the concurrency guard `expected_contract_version` from §2.7. The checks run in order: the contract must resolve (`ERR_CONTRACT_NOT_FOUND`); the stale-version guard rejects an outdated view with `ERR_STALE_VERSION` (HTTP 412), and the contract must currently be `ACTIVE`, failing with `ERR_CONTRACT_INVALID_STATE` otherwise; then the notice period is measured in whole days from `notice_date` to `termination_date` and must be at least ninety — exactly ninety days is accepted, eighty-nine is rejected with `ERR_NOTICE_PERIOD_INSUFFICIENT` (HTTP 422). A drafted notice begins with `notice_status` at `DRAFT`, its creation increments the contract's `version` by one, `NOTICE_CREATED` is appended to the audit trail, and several draft notices may coexist on one contract. A notice id that fails to resolve draws `ERR_NOTICE_NOT_FOUND`.

Issuing a notice is the point of no easy return. A `ContractManager` issues a notice that is `DRAFT` — any other notice state fails with `ERR_NOTICE_INVALID_STATE` (HTTP 409) — and whose parent contract is still `ACTIVE`. The notice moves from `DRAFT` to `ISSUED`, appending `NOTICE_ISSUED`, and the cascade moves the contract from `ACTIVE` to `TERMINATION_NOTICE`, increments the contract's `version`, and appends `TERMINATION_NOTICE_ISSUED`.

Finalization belongs to `PlanAdmin` and is gated by time itself: the notice must be `ISSUED`, and the logical clock's current date must be on or after the notice's `termination_date`; an early finalization, like any state-mismatched notice action, fails with `ERR_NOTICE_INVALID_STATE`. A successful finalization moves the notice from `ISSUED` to `EFFECTIVE` and fires the termination cascade: the contract moves from `TERMINATION_NOTICE` to `TERMINATED` — its terminal state — incrementing its `version` and appending `CONTRACT_TERMINATED`; every continuity-of-care case of the notice standing `NOTIFIED` moves to `ACTIVE_COVERAGE`, while cases still `IDENTIFIED` are left untouched; and every simulation batch under every version of the contract standing `OPEN`, `PRICED`, or `FAILED` moves to `CLOSED`, while `PASSED` batches are preserved untouched. `NOTICE_EFFECTIVE` is appended alongside.

Rescission unwinds an issued notice. A `ContractManager` rescinds a notice that is `ISSUED` (`ERR_NOTICE_INVALID_STATE` otherwise): the notice becomes `RESCINDED`, appending `NOTICE_RESCINDED`, and the compensating cascade returns the contract from `TERMINATION_NOTICE` to `ACTIVE`, increments its `version`, appends `TERMINATION_NOTICE_RESCINDED`, and closes every continuity case of the notice standing `IDENTIFIED` or `NOTIFIED` by moving it to `CLOSED_RESCINDED`.

**Continuity-of-care cases** protect members in active treatment when a contract terminates. A `ContractManager` registers a case against an `ISSUED` notice — registration against any other notice state fails with `ERR_NOTICE_INVALID_STATE` — supplying a `member_ref`, a `condition_category` of `INPATIENT_CONFINEMENT`, `PREGNANCY`, `DIALYSIS`, `ONCOLOGY_TREATMENT`, or `TRANSPLANT_WORKUP`, and a `treatment_end_date`. The treatment end must fall strictly after the notice's `termination_date`; when it does not, no post-termination obligation exists and registration fails with `ERR_COC_WINDOW_EXCEEDED` (HTTP 422). At creation the case computes its `coverage_end_date` as the earlier of two dates: the notice's `termination_date` advanced by ninety days, or the case's own `treatment_end_date`. Cases begin with `case_status` at `IDENTIFIED`, bound to their notice through `termination_notice_id`. A case id that fails to resolve draws `ERR_CASE_NOT_FOUND`.

The case lifecycle then tracks the member's protection. Notification by a `ContractManager` moves a case from `IDENTIFIED` to `NOTIFIED` while its notice remains `ISSUED`. Coverage activation moves a case from `NOTIFIED` to `ACTIVE_COVERAGE` once the parent notice has become `EFFECTIVE` — this happens automatically as part of the finalization cascade for every notified case, and an explicit activation by a `ContractManager` expresses the same transition for a case that reaches `NOTIFIED` under an already-effective notice. From `ACTIVE_COVERAGE`, completion by a `ContractManager` moves the case to `COMPLETED` when treatment ends; expiry moves it to `EXPIRED` only when the logical clock's current date has passed the case's `coverage_end_date` — an expiry attempted earlier, or any action against a case in a state that does not permit it, fails with `ERR_CASE_INVALID_STATE` (HTTP 409). `COMPLETED`, `EXPIRED`, and `CLOSED_RESCINDED` are the terminal dispositions of a case.


## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including every lifecycle transition, cascade trigger, and clock adjustment — return a `200 OK` status code. In the table below, "All roles" means the six roles declared in §2.1; "All except ProviderRep" means the five internal roles. Authorization is enforced exactly as listed, and the ownership scoping of §2.1 applies in addition on the eight reads it enumerates.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/networks` | Create a network | PlanAdmin |
| GET | `/networks` | List networks, optionally filtered by line of business | All roles |
| GET | `/networks/{id}` | Get one network | All roles |
| POST | `/networks/{id}/retire` | Retire a network (`ACTIVE` to `RETIRED`) | PlanAdmin |
| GET | `/networks/{id}/contracts` | List contracts participating in a network | All except ProviderRep |
| POST | `/medicare-benchmarks` | Create a Medicare benchmark row in `DRAFT` | PlanAdmin |
| GET | `/medicare-benchmarks` | List benchmarks with optional filters | All roles |
| GET | `/medicare-benchmarks/{id}` | Get one benchmark | All roles |
| POST | `/medicare-benchmarks/{id}/publish` | Publish a benchmark (`DRAFT` to `PUBLISHED`) | PlanAdmin |
| POST | `/rate-parity-rules` | Create a rate parity rule between two lines of business | PlanAdmin |
| GET | `/rate-parity-rules` | List rate parity rules | All roles |
| GET | `/rate-parity-rules/{id}` | Get one rate parity rule | All roles |
| POST | `/providers` | Register a provider | PlanAdmin |
| GET | `/providers` | List providers (paginated) | All roles |
| GET | `/providers/{id}` | Get one provider | All roles |
| POST | `/providers/{id}/contracts` | Create a contract for a provider (starts `DRAFT`) | ContractManager |
| GET | `/providers/{id}/contracts` | List a provider's contracts | All roles |
| GET | `/contracts/{id}` | Get one contract | All roles |
| POST | `/contracts/{id}/begin-negotiation` | Move a draft contract into negotiation | ContractManager |
| POST | `/contracts/{id}/submit-for-signature` | Submit negotiated terms for signature | ContractManager |
| POST | `/contracts/{id}/counter-offer` | Return a submitted contract to negotiation | ContractManager |
| POST | `/contracts/{id}/sign` | Sign a submitted contract (segregated from submitter) | ContractLegal |
| POST | `/contracts/{id}/begin-configuration` | Enter configuration (initial build or amendment cycle) | ConfigurationAnalyst |
| POST | `/contracts/{id}/begin-testing` | Enter configuration testing (requires a `VALIDATED` version) | ConfigurationAnalyst |
| POST | `/contracts/{id}/return-to-configuration` | Return from testing to configuration | ConfigurationAnalyst |
| POST | `/contracts/{id}/mark-ready` | Mark the contract ready for go-live (requires a `PASSED` batch) | ConfigurationAnalyst |
| POST | `/contracts/{id}/approve-go-live` | Approve go-live, enforce parity, activate the validated version | PlanAdmin |
| POST | `/contracts/{id}/versions` | Create an amendment version (OCC-guarded) | ContractManager |
| GET | `/contracts/{id}/versions` | List versions of a contract | All roles |
| GET | `/contract-versions/{id}` | Get one contract version | All roles |
| POST | `/contract-versions/{id}/load` | Load a version (also reloads a rejected version to `DRAFT`) | ConfigurationAnalyst |
| POST | `/contract-versions/{id}/validate` | Validate a loaded version (locking entries) or reject it | ConfigurationAnalyst |
| POST | `/contract-versions/{id}/fee-schedule-entries` | Add a fee schedule entry | ConfigurationAnalyst |
| GET | `/contract-versions/{id}/fee-schedule-entries` | List entries of a version | All roles |
| GET | `/fee-schedule-entries` | Filtered list of entries across versions | All except ProviderRep |
| GET | `/fee-schedule-entries/{id}` | Get one entry | All roles |
| POST | `/fee-schedule-entries/{id}/map-benchmark` | Resolve the benchmark and compute the entry's base rate | ConfigurationAnalyst |
| POST | `/contract-versions/{id}/carve-outs` | Add a contract-language carve-out | ContractLegal |
| GET | `/contract-versions/{id}/carve-outs` | List carve-outs of a version | All roles |
| GET | `/carve-outs/{id}` | Get one carve-out | All roles |
| POST | `/contract-versions/{id}/simulation-batches` | Create a simulation batch (starts `OPEN`) | ConfigurationAnalyst |
| GET | `/contract-versions/{id}/simulation-batches` | List simulation batches of a version | All roles |
| GET | `/simulation-batches/{id}` | Get one batch with its counters | All roles |
| POST | `/simulation-batches/{id}/claims` | Add a test claim to an open batch | ConfigurationAnalyst |
| GET | `/simulation-batches/{id}/claims` | List claims of a batch | All roles |
| POST | `/simulation-batches/{id}/price` | Price all pending claims (`OPEN` to `PRICED`) | ConfigurationAnalyst |
| POST | `/simulation-batches/{id}/score` | Score a priced batch (to `PASSED` or `FAILED`) | ConfigurationAnalyst |
| POST | `/simulation-batches/{id}/reopen` | Reopen a failed batch, resetting its claims | ConfigurationAnalyst |
| POST | `/contracts/{id}/paid-claims` | Load a paid claim snapshot (contract must be `ACTIVE`) | PaymentIntegrityAnalyst |
| GET | `/contracts/{id}/paid-claims` | List paid claim snapshots of a contract | All except ProviderRep |
| GET | `/paid-claims/{id}` | Get one paid claim snapshot | All except ProviderRep |
| GET | `/contract-versions/{id}/retro-adjustment-runs` | List retro adjustment runs of a version | All except ProviderRep |
| GET | `/retro-adjustment-runs/{id}` | Get one retro run with its totals | All except ProviderRep |
| POST | `/retro-adjustment-runs/{id}/compute` | Sweep paid claims and create proposed adjustments | PaymentIntegrityAnalyst |
| POST | `/retro-adjustment-runs/{id}/finalize` | Finalize a computed run, adjusting referenced snapshots | PaymentIntegrityAnalyst |
| POST | `/retro-adjustment-runs/{id}/void` | Void a computed run, voiding its proposed adjustments | PaymentIntegrityAnalyst |
| GET | `/retro-adjustment-runs/{id}/adjustments` | List adjustments of a run | All except ProviderRep |
| GET | `/retro-adjustments` | Filtered list of adjustments | All except ProviderRep |
| GET | `/retro-adjustments/{id}` | Get one adjustment | All except ProviderRep |
| POST | `/retro-adjustments/{id}/approve` | Approve a proposed adjustment | PaymentIntegrityAnalyst |
| POST | `/retro-adjustments/{id}/reject` | Reject a proposed adjustment | PaymentIntegrityAnalyst |
| POST | `/retro-adjustments/{id}/settle` | Settle an approved adjustment by direction | PaymentIntegrityAnalyst |
| POST | `/contracts/{id}/termination-notices` | Draft a termination notice (OCC-guarded; contract must be `ACTIVE`) | ContractManager |
| GET | `/contracts/{id}/termination-notices` | List termination notices of a contract | All except ProviderRep |
| GET | `/termination-notices/{id}` | Get one termination notice | All except ProviderRep |
| POST | `/termination-notices/{id}/issue` | Issue a notice, moving the contract to `TERMINATION_NOTICE` | ContractManager |
| POST | `/termination-notices/{id}/finalize` | Finalize a notice, terminating the contract | PlanAdmin |
| POST | `/termination-notices/{id}/rescind` | Rescind a notice, restoring the contract to `ACTIVE` | ContractManager |
| POST | `/termination-notices/{id}/continuity-cases` | Register a continuity-of-care case on an issued notice | ContractManager |
| GET | `/termination-notices/{id}/continuity-cases` | List continuity cases of a notice | All except ProviderRep |
| GET | `/continuity-cases/{id}` | Get one continuity-of-care case | All except ProviderRep |
| POST | `/continuity-cases/{id}/notify` | Mark a case as notified | ContractManager |
| POST | `/continuity-cases/{id}/activate-coverage` | Activate coverage for a notified case | ContractManager |
| POST | `/continuity-cases/{id}/complete` | Complete a case in active coverage | ContractManager |
| POST | `/continuity-cases/{id}/expire` | Expire a case past its coverage end date | ContractManager |
| GET | `/contracts/{id}/audit-events` | List the contract's append-only audit trail | All roles |
| GET | `/audit-events/{id}` | Get one audit event | All except ProviderRep |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlanAdmin |

## 5. Error Code Catalogue

Trigger conditions for every error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status code.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_NETWORK_NOT_FOUND` | 404 Not Found |
| `ERR_BENCHMARK_NOT_FOUND` | 404 Not Found |
| `ERR_PARITY_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_VERSION_NOT_FOUND` | 404 Not Found |
| `ERR_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_CARVE_OUT_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_PAID_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_ADJUSTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_INVALID_STATE` | 409 Conflict |
| `ERR_VERSION_INVALID_STATE` | 409 Conflict |
| `ERR_ENTRY_INVALID_STATE` | 409 Conflict |
| `ERR_BATCH_INVALID_STATE` | 409 Conflict |
| `ERR_ADJUSTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_RUN_INVALID_STATE` | 409 Conflict |
| `ERR_NOTICE_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_BENCHMARK_INVALID_STATE` | 409 Conflict |
| `ERR_RATE_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_COC_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NOTICE_PERIOD_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_VERSION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CARVE_OUT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_RETRO_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_BENCHMARK` | 409 Conflict |
| `ERR_DUPLICATE_VERSION_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_SERVICE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM_NUMBER` | 409 Conflict |
| `ERR_BATCH_EMPTY` | 422 Unprocessable Entity |
| `ERR_BENCHMARK_UNRESOLVABLE` | 422 Unprocessable Entity |
| `ERR_BENCHMARK_UNPUBLISHED` | 422 Unprocessable Entity |
| `ERR_NETWORK_INACTIVE` | 422 Unprocessable Entity |
| `ERR_NO_VALIDATED_VERSION` | 422 Unprocessable Entity |
| `ERR_RATE_PARITY_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SIMULATION_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
