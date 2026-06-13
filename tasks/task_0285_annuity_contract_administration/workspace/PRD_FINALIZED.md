# Annuity Contract Administration API — Product Requirements Document

## 1. Introduction

The Annuity Contract Administration API is the system of record for the full economic life of deferred-annuity contracts: how they are funded, how value accumulates through crediting, how money leaves through penalty-free corridors and surrender-charge-bearing withdrawals, and how the contract ultimately resolves through annuitization, a death claim, or a tax-free 1035 exchange to another carrier. The platform supports three product families — fixed-rate contracts that credit a guaranteed annual rate, variable contracts whose value rides a basket of investment divisions, and indexed contracts that credit a capped-and-floored share of a reference index — and each family carries its own crediting arithmetic while sharing one common ledger discipline.

A central design tension drives the requirements: every monetary movement must be reconstructable from an append-only history of funding, crediting, and withdrawal events, yet several actors operate on the same contract concurrently. Premiums are submitted and cleared by contract administrators, crediting is posted by a separate crediting desk, and withdrawals, death claims, and 1035 exchanges are reviewed by compliance — a deliberate segregation of duties in which the person who submits a tax-free exchange may never be the person who approves it. Because a contract's accumulation value is the basis against which charges, projections, and benefits are sized, the API guards mutations with optimistic concurrency control so that a writer acting on a stale picture of the contract is turned away rather than allowed to corrupt the ledger.

This document specifies the resources, lifecycles, calculations, and guardrails that any conforming implementation must honor. It is written for the engineer building the service: domain rules first, wire-level contract second.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly three roles, spelled precisely as follows:

- `ContractAdmin` — sets up products, contracts, premiums, sub-account allocations, index segments, and beneficiaries; files death claims; elects annuitizations; drafts and submits 1035 exchanges; and operates the test-driving clock endpoints.
- `CreditingOfficer` — posts crediting events (guaranteed interest, index-segment, and sub-account returns); read-only everywhere else.
- `ComplianceOfficer` — settles or rejects withdrawals; processes death claims through verification, valuation, funding, and denial; and requests revisions on, approves, rejects, and settles 1035 exchanges. A `ComplianceOfficer` may never submit a 1035 exchange.

All three roles share read access to the collection and detail (GET) endpoints, with one narrowing: the 1035-exchange list and detail views are visible only to `ContractAdmin` and `ComplianceOfficer`, not to `CreditingOfficer`.

Each of the three roles carries an **opaque** identity. That is, when `X-User-Role` is `ContractAdmin`, `CreditingOfficer`, or `ComplianceOfficer`, the accompanying `X-User-ID` is an operator identifier that is not tied to any persisted entity's `id`; the server never compares it to a resource's foreign key for ownership purposes. The server may, however, record an operator's `X-User-ID` where a transition explicitly captures it — specifically, when a 1035 exchange is submitted the submitter's `X-User-ID` is retained on the exchange so that the later segregation-of-duties check at approval time can confirm the approver's `X-User-ID` differs from it. Outside that one recorded use, identity is not persisted and never gates ownership.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Most resources in the system carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp recording the resource's most recent modification; it advances on every mutation.
- `version` — an integer that starts at its initial value and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control described in §2.6.

One resource departs from this convention. A `CreditingEvent` is an append-only ledger entry that is never modified after it is posted; it therefore carries only `id` and `created_at`, and has neither an `updated_at` nor a `version` field. Every other resource — `Product`, `Contract`, `Premium`, `SubAccountAllocation`, `IndexSegment`, `Withdrawal`, `Beneficiary`, `Annuitization`, `DeathClaim`, and `Exchange1035` — carries the full set including `updated_at` and `version`.

### 2.5. Hierarchical Consistency and Automatic Cascades

The contract is the aggregate root, and a number of its child resources can drive the contract's own status without an explicit client call against the contract itself. When the first premium on a contract clears, when a full-surrender withdrawal settles, when an annuitization begins paying out, when a death claim is filed or funded or denied — in each case the contract's status moves automatically as a side effect of the child operation. Whenever such a cascade fires, the contract's `version` increments by one and its `updated_at` is refreshed, exactly as it would for a direct mutation. The same is true of the system-driven anniversary roll and of crediting and premium-clearing operations that change accumulation: each one bumps `Contract.version`. These cascades are detailed in §3 alongside the workflows that trigger them; the principle here is simply that a derived change to the parent is a real mutation and is versioned as one.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded against stale reads, because each one is sized against, or acts upon, a contract or exchange whose state another writer may have advanced. On these operations the client must supply the version it last observed on the parent, and the server rejects the request if that version no longer matches the live parent.

- Requesting a withdrawal requires `expected_contract_version` to carry the `version` the client last read on the target `Contract`. If another writer has since cleared a premium, settled an earlier withdrawal, or rolled an anniversary — any of which legitimately changes the accumulation value the new withdrawal would be sized against — the contract's `version` has advanced and the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412).
- Submitting a subsequent premium likewise requires `expected_contract_version` to match the target `Contract`'s current `version`; a mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), since the funding picture the client observed is no longer current.
- Approving a 1035 exchange requires `expected_exchange_version` to match the target `Exchange1035`'s current `version`. Because a request-revision-and-resubmit cycle bumps the exchange's version, an approval carrying a stale version refers to a superseded revision and is rejected with `ERR_STALE_EXCHANGE_VERSION` (HTTP 412).

These three are the only version-bearing inputs in the API. Every other write operation omits the version field entirely and is not subject to an OCC check.

### 2.7. Money, Rates, and Rounding

All monetary amounts are integer cents; there are no fractional-cent values anywhere in the system, and bps (basis points) are integers where 10000 bps equals 100%. Where a calculation produces a fractional cent, the result is resolved to a whole cent using **round half up** unless a rule explicitly calls for flooring. Two computations floor rather than round: the penalty-free corridor allowance, and each beneficiary's floored share of a death benefit (with the leftover penny handled as described in §3). The chronological accumulation value and the death-benefit valuation involve no rounding at all, since their inputs are already whole cents. Each crediting and surrender calculation states its own rounding posture in §3; where "round half up" is named, the half-cent case always rounds away from zero to the next whole cent.

### 2.8. Nested Resource Retrieval and Existence Ordering

Several read endpoints reach a contract's children by walking the contract in the path — for example, listing the premiums, withdrawals, crediting events, beneficiaries, sub-account allocations, index segments, annuitizations, or death claims that belong to a given contract. For any path that names a resource, the server validates existence left to right and rejects the first identifier in the path that does not resolve to a live resource with `ERR_RESOURCE_NOT_FOUND` (HTTP 404). A foreign-key field carried in a request body — such as `contract_id`, `product_id`, `source_segment_id`, `source_allocation_id`, `source_contract_id`, `target_contract_id`, or `source_exchange_id` — that points at a non-existent resource is instead rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404). The distinction is deliberate: a missing path resource and a missing referenced resource carry different error identifiers though both are 404.

### 2.9. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing or malformed header yields `ERR_UNAUTHENTICATED` (401). Role authorization comes next: a role not permitted for the operation yields `ERR_FORBIDDEN_ROLE` (403). Then path-resource existence is checked left to right (`ERR_RESOURCE_NOT_FOUND`, 404), followed by referenced foreign-key existence in the body (`ERR_REFERENCED_RESOURCE_NOT_FOUND`, 404). Next comes shape and range validation of the payload — required scalar fields present and correctly typed, enum values within their declared domains, and integers within their stated ranges — which fails with `ERR_INVALID_REQUEST` (422). Only after the request is well-formed does the system apply the optimistic-concurrency check (§2.6), then the state-machine check confirming the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409), and finally the domain-specific business rules described throughout §3. In short: authentication, then authorization, then path existence, then reference existence, then request validity, then concurrency, then state legality, then business safety and fiscal rules — in that order.

### 2.10. The Logical Clock and Contract Time

Because contract anniversaries, completed-year counts, and date-of-death checks all depend on wall-clock time, the system exposes an administrative clock that test harnesses drive explicitly. A `ContractAdmin` may set the server's current UTC instant by supplying a `to_iso8601` value, and may roll a named contract to its next anniversary by supplying a `contract_id`. The contract's `issue_date` is stamped from the server clock at the moment its first premium clears, and `contract_year` — the count of completed contract years since issue, computed as the floor of the elapsed time since `issue_date` divided by 365 days — derives from that stamp against the current clock. `contract_year` is 0 throughout the first year and drives the surrender-charge schedule lookup.

## 3. Business Logic & Workflows

### 3.1. Products: the Configuration Template

Every contract is instantiated from a **Product**, a reusable template that a `ContractAdmin` defines up front. A product carries a display `name` and a `contract_type` that is one of `FIXED`, `VARIABLE`, or `INDEXED`. A fixed product additionally declares a `fixed_annual_rate_bps` — its guaranteed annual crediting rate in basis points, where 350 means 3.50% — and this field is required when `contract_type` is `FIXED` and must be absent (null) for the other two types. The product also names its `death_benefit_type`, one of `RETURN_OF_PREMIUM`, `ACCOUNT_VALUE`, or `HIGHEST_ANNIVERSARY`, which selects the death-benefit valuation rule described in §3.9.

The product configures the contract's withdrawal economics. The `free_withdrawal_corridor_bps` sets the annual penalty-free withdrawal allowance as a fraction of the prior-anniversary accumulation value, defaulting to 1000 (that is, 10.00%). The `mva_enabled` flag, defaulting to false, decides whether a Market Value Adjustment applies to surrender-charge-bearing withdrawals. The `surrender_charge_schedule` is an ordered array of rows, each row pairing a `contract_year` of at least 1 with a `charge_bps` of at least 0; the row at position equal to the contract's current completed year supplies that year's charge rate, and the array's length is the surrender period in years. Finally, `min_initial_premium_cents` sets the floor on the first premium, defaulting to 1,000,000 cents — that is, ten thousand dollars.

A product's `status` is `ACTIVE` when created and may be moved to `RETIRED` by a `ContractAdmin`; a `RETIRED` product rejects any attempt to open a new contract against it. Retiring a product is a state change on the product and returns the product with its status updated.

### 3.2. Opening and Funding a Contract

A `ContractAdmin` opens a **Contract** by naming the `product_id` of an `ACTIVE` product, the `owner_name`, and the `annuitant_age`, which must be a whole number of years from 0 through 85 inclusive. The contract is born in `PENDING` status with an accumulation value of zero; its `issue_date`, `contract_year`, `accumulation_value_cents`, `cumulative_premium_cents`, `highest_anniversary_value_cents`, `free_withdrawal_used_cents`, and `surrender_charge_bps` are all system-computed and start empty or zero. The contract's `status` ranges over `PENDING`, `ACTIVE`, `ANNUITIZED`, `SURRENDERED`, `DEATH_CLAIM`, and `TERMINATED`; the latter three of those — `SURRENDERED`, `ANNUITIZED`, and `TERMINATED` — are terminal.

Funding flows through **Premium** resources. A premium is submitted with the `contract_id` it funds, a `gross_premium_cents` amount that must be greater than zero, an optional `premium_load_bps` sales load between 0 and 1000 that defaults to 0, and an optional `source_exchange_id` linking it to an inbound 1035 exchange (null for ordinary cash premiums). For a subsequent premium the request must also carry `expected_contract_version` for the OCC check of §2.6. The server determines `is_initial` — true exactly when this is the first premium on the contract — and sets the premium's `status` to `SUBMITTED`. A premium against a `PENDING` contract is treated as the initial premium; a premium against an `ACTIVE` contract is a subsequent one. The initial premium's `gross_premium_cents` must be at least the product's `min_initial_premium_cents`, and falling short is rejected with `ERR_BELOW_MINIMUM_PREMIUM`.

Clearing is the act that moves money onto the ledger. When a `ContractAdmin` clears a premium that is in `SUBMITTED` status, the server computes its `net_premium_cents` as the gross amount multiplied by one minus the load fraction — that is, `gross_premium_cents` times the quantity one minus `premium_load_bps` divided by 10000 — rounded half up to a whole cent. The net amount is added into both `accumulation_value_cents` and `cumulative_premium_cents`, and `Contract.version` increments. Clearing the **initial** premium additionally drives the contract from `PENDING` to `ACTIVE`: at that moment the server stamps `issue_date` to the current clock, recomputes the accumulation and cumulative-premium totals to include the just-cleared net premium, and sets `highest_anniversary_value_cents` equal to the new accumulation value. A clear may be requested only while the premium is `SUBMITTED` and only while the contract is in the matching state — `PENDING` for an initial premium or `ACTIVE` for a subsequent one — otherwise it is rejected with `ERR_INVALID_STATE`. A `ContractAdmin` may instead reject a `SUBMITTED` premium, moving it to `REJECTED` with no change to accumulation; if that premium had been funded by an inbound exchange, the exchange remains in its approved posture and a fresh premium must be submitted to settle it. A premium ends in one of two terminal states, `CLEARED` or `REJECTED`.

For a `VARIABLE` contract, the initial premium cannot clear until the contract's sub-account allocations are complete. A `ContractAdmin` adds a **SubAccountAllocation** by naming the `contract_id`, a `division_name`, an `allocation_bps` share between 1 and 10000, and the division's current `unit_value_cents`. An allocation begins `ACTIVE` and is set to `LIQUIDATED` when the contract surrenders or annuitizes. The sum of `allocation_bps` across all `ACTIVE` allocations on the contract must equal exactly 10000 before the initial premium may clear; a partial set of allocations causes the clear to be rejected with `ERR_ALLOCATION_INCOMPLETE`.

### 3.3. Crediting: Three Engines, One Ledger

Crediting adds value to a contract's accumulation, and a `CreditingOfficer` is the only role that may post a **CreditingEvent**. Every event names its `contract_id` and a `crediting_kind` that must agree with the contract's product type: `FIXED_GUARANTEED` only on a `FIXED` contract, `INDEX_SEGMENT` only on an `INDEXED` contract, and `SUBACCOUNT_RETURN` only on a `VARIABLE` contract. A kind that does not match the product type, or an `INDEX_SEGMENT` event missing its `source_segment_id`, or a `SUBACCOUNT_RETURN` event missing its `source_allocation_id`, is rejected with `ERR_CREDITING_KIND_MISMATCH`. When the event posts, the server computes its `credit_cents`, adds that amount to `accumulation_value_cents`, stamps the event's `posted_period_index` from the server crediting-period counter, and increments `Contract.version`. A `CreditingEvent` is append-only and never bears a negative credit.

The credit amount depends on the kind. For **guaranteed** crediting (`FIXED_GUARANTEED`), the credit is the contract's current `accumulation_value_cents` multiplied by the product's `fixed_annual_rate_bps` divided by 10000, rounded half up. For an **index segment** (`INDEX_SEGMENT`), the event carries the period's `raw_index_return_bps` together with `credit_period_start` and `credit_period_end`; the server first scales the raw return by the segment's participation, taking `raw_index_return_bps` multiplied by the segment's `participation_bps` divided by 10000, then caps that participated return at the segment's `cap_bps` by taking the smaller of the two, then floors the result at the segment's `floor_bps` by taking the larger of the capped value and the floor, and finally multiplies the segment's `segment_premium_cents` by that bounded rate divided by 10000, rounded half up. For a **sub-account return** (`SUBACCOUNT_RETURN`), the `raw_index_return_bps` is reused as the division's period return; the server takes the allocation's share of the contract — `accumulation_value_cents` multiplied by the allocation's `allocation_bps` divided by 10000 — and multiplies that share by the division return divided by 10000, rounded half up. In every kind the computed `credit_cents` is floored at zero so a credit is never negative.

Before any index crediting can occur, a `ContractAdmin` opens an **IndexSegment** by naming the `contract_id`, the `index_name`, a half-open term window from an inclusive `term_start_date` to an exclusive `term_end_date` (the start must precede the end), the `segment_premium_cents` allocated to the term (which must be greater than zero), the `cap_bps` upper bound on credited return, an optional `floor_bps` lower bound defaulting to 0, and an optional `participation_bps` defaulting to 10000 (100%). A segment is born `OPEN`. Two `OPEN` segments on the same contract and `index_name` may not overlap, but they may abut: adjacency where one term's `term_end_date` exactly equals the next term's `term_start_date` (a zero-length gap) is allowed. The overlap test rejects a new segment when its start falls before an existing segment's end and that existing segment's start falls before the new segment's end; such a collision is rejected with `ERR_SEGMENT_TERM_OVERLAP`. When an `INDEX_SEGMENT` crediting event posts against an `OPEN` segment, that segment moves from `OPEN` to `CREDITED`, and a `CREDITED` segment rejects any further index-segment crediting.

Index crediting periods are policed more strictly than segment terms. The `credit_period_start` (inclusive) and `credit_period_end` (exclusive) of an `INDEX_SEGMENT` event must lie inside the source segment's term window, and must neither overlap nor merely touch any prior crediting period for the same segment. Unlike segment terms, adjacency is forbidden here: a new crediting period whose start exactly equals a prior period's end, or whose end exactly equals a prior period's start, is rejected — as is any genuine overlap where the new start precedes a prior end while the prior start precedes the new end. Any of these collisions, or a period that falls outside the segment's term window, is rejected with `ERR_CREDIT_PERIOD_OVERLAP`.

### 3.4. The Anniversary Roll

Each contract year, an anniversary roll resets the year's penalty-free budget and captures a high-water mark. Driven as an administrative system event against an `ACTIVE` contract, the roll sets `highest_anniversary_value_cents` to the larger of its prior value and the current `accumulation_value_cents`, resets `free_withdrawal_used_cents` to zero, recomputes `contract_year` and the derived `surrender_charge_bps` against the advanced clock, and increments `Contract.version`. The `surrender_charge_bps` is read from the product's `surrender_charge_schedule` at the index equal to the current `contract_year`; once `contract_year` reaches or exceeds the schedule's length the contract is past its surrender period and `surrender_charge_bps` is 0.

### 3.5. Withdrawals: Corridor, Charge, and Market Adjustment

A `ContractAdmin` requests a **Withdrawal** against an `ACTIVE` contract by naming the `contract_id`, the `requested_amount_cents` the owner wishes to receive (greater than zero), an optional `is_full_surrender` flag defaulting to false, and `expected_contract_version` for the OCC guard of §2.6. The withdrawal is born `REQUESTED`. Its computed fields — `free_amount_cents`, `chargeable_amount_cents`, `surrender_charge_cents`, `mva_cents`, and `gross_withdrawal_cents` — are not finalized at request time; they are computed when a `ComplianceOfficer` settles the withdrawal. A withdrawal ends in `SETTLED` or `REJECTED`. A `ComplianceOfficer` may reject a `REQUESTED` withdrawal, moving it to `REJECTED` with no change to `accumulation_value_cents` or `free_withdrawal_used_cents`.

Settling a withdrawal computes the money in a strictly pinned order: first the corridor split, then the surrender charge on whatever remains chargeable, then the market value adjustment on that same chargeable remainder. The **corridor split** works as follows. The annual penalty-free allowance is the floor of the contract's `highest_anniversary_value_cents` multiplied by the product's `free_withdrawal_corridor_bps` divided by 10000; this is the prior-anniversary snapshot used as the corridor basis. The remaining corridor is that allowance minus the `free_withdrawal_used_cents` already consumed this year, never less than zero. The `free_amount_cents` of this withdrawal is the smaller of the requested amount and the remaining corridor, so a withdrawal exactly equal to the remaining corridor is entirely free, while one cent beyond it makes exactly that one cent chargeable. The `chargeable_amount_cents` is the requested amount minus the free portion.

The **surrender charge** then applies to the chargeable remainder. The charge rate is the contract's `surrender_charge_bps` for the current completed `contract_year` — the schedule row described in §3.4 — and `surrender_charge_cents` is the chargeable amount multiplied by that rate divided by 10000, rounded half up. When the contract is past its surrender period the rate is 0 and the surrender charge is therefore 0 regardless of the chargeable amount; within the surrender period the schedule row applies. A withdrawal that lands entirely inside the corridor has a chargeable amount of 0 and therefore no charge.

The **Market Value Adjustment** applies only when the product's `mva_enabled` is true; otherwise `mva_cents` is 0. When enabled, the MVA is computed on the chargeable remainder after the surrender charge is fixed. The server determines the years remaining in the surrender period as the schedule length minus the current `contract_year`, never less than zero, then a rate differential equal to a market reference of 500 bps minus the product's `fixed_annual_rate_bps` (or, when the product carries no fixed rate, an assumed growth rate of 400 bps). The `mva_cents` is the chargeable amount multiplied by that rate differential, multiplied by the years remaining, divided by 1,000,000, rounded half up. The result is signed: a positive `mva_cents` increases the total withdrawal (market rates rose, so a penalty), while a negative `mva_cents` decreases it (market rates fell, so a bonus).

The total reduction of the contract is the `gross_withdrawal_cents`, equal to `requested_amount_cents` plus `surrender_charge_cents` plus `mva_cents` (where the MVA term may be negative and thus reduce the gross). At settle time, this gross must not exceed the contract's current `accumulation_value_cents`; an over-draw is rejected with `ERR_INSUFFICIENT_ACCUMULATION`. A settle is permitted only while the withdrawal is `REQUESTED` and the contract is `ACTIVE`. On a successful settle the server debits `accumulation_value_cents` by the gross, increases `free_withdrawal_used_cents` by the free portion, and increments `Contract.version`. If the withdrawal carried `is_full_surrender` set to true, settling it also liquidates the entire accumulation and cascades the contract from `ACTIVE` to `SURRENDERED`: the contract's `accumulation_value_cents` is set to 0, every `ACTIVE` sub-account allocation on the contract is set to `LIQUIDATED`, and `Contract.version` increments for the cascade.

The accumulation value the system reports is always a chronological ledger replay, not a running counter. To read it, the server replays the contract's value-bearing events in `created_at` ascending order — adding each `CLEARED` premium's `net_premium_cents`, adding each crediting event's `credit_cents`, and subtracting each `SETTLED` withdrawal's `gross_withdrawal_cents` — and floors the running total at zero. Submitted-but-not-cleared premiums and requested-but-not-settled withdrawals are excluded from this replay. Ties in `created_at` are broken by insertion order; the resource `id` is never used as an ordering key. This replay is recomputed on every premium clear, crediting post, and withdrawal settle, and whenever a contract is retrieved.

### 3.6. Forward-Looking Maturity Projection

Separate from the settled chronological value, the system can project a contract's value to the end of its surrender period assuming the current crediting posture continues. This projection starts from the settled chronological accumulation value as its base and, by default, also adds the net amounts of all `SUBMITTED` (not-yet-cleared) premiums as if they will clear — this inclusion of pending premiums is the one difference from the chronological value. The number of years to project is the schedule length minus the current `contract_year`, never less than zero. The growth rate is the product's `fixed_annual_rate_bps` for a fixed product, or an assumed growth rate of 400 bps otherwise. For each remaining year the projected value is multiplied by one plus the rate divided by 10000 and rounded half up, compounding year over year. The response reports the projected maturity value, the settled base it started from, and the number of years projected.

The projection has two variants selected by the `include_pending` query parameter. With `include_pending` true — the default — the `SUBMITTED` premium net amounts are folded into the base before projecting. With `include_pending` false, those pending premiums are excluded and the projection runs from the settled chronological base alone; the same contract therefore yields a different number under the two settings.

### 3.7. Beneficiaries

A `ContractAdmin` designates a **Beneficiary** on a contract by naming the `contract_id`, the beneficiary's `full_name`, a `relationship` that is one of `SPOUSE`, `CHILD`, `TRUST`, `ESTATE`, or `OTHER`, and a `share_bps` between 1 and 10000. A beneficiary begins `ACTIVE` with a `payout_cents` of 0 and may be moved to `REVOKED` by a `ContractAdmin`; a `REVOKED` beneficiary is excluded both from the share-completeness sum and from any death-benefit distribution. Before a death claim may be funded, the sum of `share_bps` across all `ACTIVE` beneficiaries must equal exactly 10000.

### 3.8. Annuitization

A `ContractAdmin` elects an **Annuitization** against an `ACTIVE` contract by naming the `contract_id`, a `payout_option` that is one of `LIFE_ONLY`, `PERIOD_CERTAIN`, `LIFE_WITH_PERIOD_CERTAIN`, or `JOINT_LIFE`, and, where the option requires it, a `period_certain_years`. The arity rule is exact: `period_certain_years` must be present and at least 1 for `PERIOD_CERTAIN` and `LIFE_WITH_PERIOD_CERTAIN`, and must be absent for `LIFE_ONLY` and `JOINT_LIFE`; a violation is rejected with `ERR_PAYOUT_OPTION_ARITY`. An annuitization is born `ELECTED` and ends in either `ACTIVE_PAYOUT` or `DECLINED`. A `ContractAdmin` may decline an `ELECTED` annuitization, moving it to `DECLINED` with no change to the contract, which remains `ACTIVE`.

Beginning payout is the consequential transition. A `ContractAdmin` begins payout on an `ELECTED` annuitization only when the contract is `ACTIVE` and its `accumulation_value_cents` is strictly greater than zero. On success the server snapshots `annuitization_value_cents` from the contract's current accumulation, computes the `monthly_benefit_cents`, liquidates every `ACTIVE` sub-account allocation to `LIQUIDATED`, cascades the contract from `ACTIVE` to `ANNUITIZED`, sets the contract's `accumulation_value_cents` to 0 (the value having been converted to an income stream), and increments `Contract.version`.

The `monthly_benefit_cents` is built from the snapshot value, the payout option, and the annuitant's age. Begin with the snapshot `annuitization_value_cents` expressed per one thousand dollars — that is, the snapshot divided by 100,000 — multiplied by an age factor selected from a coarse age band: 480 when the annuitant's age is under 60, 540 from 60 through 69, 640 from 70 through 79, and 820 at 80 or above. That per-thousand base is then multiplied by an option percentage, applied as a percentage (divide by 100): 100 for `LIFE_ONLY`, 92 for `PERIOD_CERTAIN`, 88 for `LIFE_WITH_PERIOD_CERTAIN`, and 84 for `JOINT_LIFE`. For the two period-certain options, the result is further scaled by a haircut percentage keyed on the guaranteed years (again divide by 100): 100 for 10 years, 96 for 15 years, and 92 for 20 years. The final monthly figure is rounded half up to whole cents, and rounding is applied only at this final step.

### 3.9. Death Claims

When an owner dies, a `ContractAdmin` files a **DeathClaim** against an `ACTIVE` contract by naming the `contract_id` and the `date_of_death`, which must not be after the current server clock; a future date of death is rejected with `ERR_FUTURE_DATE_OF_DEATH`. A contract may have only one open claim — filing is refused if a claim is already `FILED`, `VERIFYING`, `VALUED`, or `FUNDED` on the contract. Filing a claim cascades the contract from `ACTIVE` to `DEATH_CLAIM`, which **freezes** the contract, and increments `Contract.version`. While a contract is frozen by an open claim (one in `FILED`, `VERIFYING`, or `VALUED`), the system refuses to create new withdrawals, new premiums, or new annuitizations on it, and refuses to clear premiums or settle withdrawals against it, in each case with `ERR_CONTRACT_FROZEN`. The claim's own fields — `identity_verified`, `benefit_valued`, and `death_benefit_cents` — start unset and are filled by the workflow below; a claim ranges over `FILED`, `VERIFYING`, `VALUED`, `FUNDED`, and `DENIED`.

The claim is processed as a fork-join by a `ComplianceOfficer`. The first branch, verify-identity, moves the claim from `FILED` to `VERIFYING` and sets `identity_verified` to true. The second branch, value-benefit, moves the claim from `VERIFYING` to `VALUED`, requires that `identity_verified` already be true, sets `benefit_valued` to true, and computes the `death_benefit_cents`. Funding then joins both branches: it moves the claim from `VALUED` to `FUNDED` only when both `identity_verified` and `benefit_valued` are true and the `ACTIVE` beneficiary shares sum to exactly 10000 (otherwise `ERR_BENEFICIARY_SHARES_INCOMPLETE`). Funding distributes the death benefit across the `ACTIVE` beneficiaries, cascades the contract from `DEATH_CLAIM` to `TERMINATED`, sets the contract's `accumulation_value_cents` to 0, and increments `Contract.version`. At any point while the claim is `FILED`, `VERIFYING`, or `VALUED`, a `ComplianceOfficer` may deny it, moving it to `DENIED` and cascading the contract from `DEATH_CLAIM` back to `ACTIVE` — un-freezing it — with `Contract.version` incremented. Each transition is rejected with `ERR_INVALID_STATE` if the claim is not in the state from which that transition is defined.

The `death_benefit_cents` computed at value-benefit time depends on the product's `death_benefit_type`. For `RETURN_OF_PREMIUM`, the benefit is the larger of the contract's `cumulative_premium_cents` and its `accumulation_value_cents`. For `ACCOUNT_VALUE`, it is simply the contract's `accumulation_value_cents`. For `HIGHEST_ANNIVERSARY`, it is the larger of the contract's `highest_anniversary_value_cents` and its `accumulation_value_cents`. No rounding is involved, as all inputs are whole cents.

Funding distributes the benefit as a waterfall. The `ACTIVE` beneficiaries are ordered by `created_at` ascending, and each beneficiary's `payout_cents` is the floor of the total death benefit multiplied by that beneficiary's `share_bps` divided by 10000. Flooring leaves a penny remainder — the total death benefit minus the sum of the floored payouts — and that remainder is added to the `payout_cents` of the earliest-created `ACTIVE` beneficiary, never chosen by `id`. This conserves the benefit exactly: the sum of all `payout_cents` equals the death benefit to the cent.

### 3.10. 1035 Exchanges

A 1035 exchange transfers value between contracts (or to and from an external carrier) without a taxable event, and it carries a deliberate segregation of duties: a `ContractAdmin` drafts and submits it, but only a `ComplianceOfficer` may approve, reject, request revision on, or settle it. A `ContractAdmin` creates an **Exchange1035** in `DRAFT` by naming a `direction` of `INBOUND` or `OUTBOUND`, the `source_contract_id` (the relinquishing contract on an outbound, null on an inbound from an external carrier), the `target_contract_id` (the receiving contract on an inbound, null on an outbound to an external carrier), an `external_carrier` name where the non-internal leg is external, a `transfer_amount_cents` greater than zero, and a `cost_basis_cents` carried-over tax basis. The basis must lie between 0 and the transfer amount inclusive; a basis above the transfer is rejected with `ERR_INVALID_COST_BASIS`, both at creation and at submit. The exchange tracks a `revision_count` that starts at 0 and ranges in status over `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, `SETTLED`, and `REJECTED`, with `SETTLED` and `REJECTED` terminal.

The review loop is cyclic. Submitting moves the exchange from `DRAFT` to `SUBMITTED` (and re-validates that the basis does not exceed the transfer); on submission the server records the submitting operator's `X-User-ID` for the later segregation check and increments the exchange's `version`. A `ComplianceOfficer` may request a revision, moving a `SUBMITTED` exchange to `REVISION_REQUESTED` and bumping its `version`. Re-submitting a `REVISION_REQUESTED` exchange moves it back to `SUBMITTED`, increments its `revision_count` by one, and bumps its `version` — this is the revision loop. Approving a `SUBMITTED` exchange requires both that the approver's `X-User-ID` differ from the recorded submitter's `X-User-ID` — otherwise `ERR_SEGREGATION_OF_DUTIES` — and that `expected_exchange_version` match the live exchange version per §2.6, and moves it to `APPROVED` with `version` bumped. A `ComplianceOfficer` may instead reject a `SUBMITTED` exchange to `REJECTED`, bumping `version`. Each transition is rejected with `ERR_INVALID_STATE` when the exchange is not in the state from which that action is defined.

Settling closes the exchange. A `ComplianceOfficer` settles an `APPROVED` exchange, moving it to `SETTLED` and bumping `version`. For an `INBOUND` exchange, settling requires that a premium on the `target_contract_id` carrying this exchange as its `source_exchange_id` already exists and is `CLEARED`. For an `OUTBOUND` exchange, settling triggers a full surrender on the `source_contract_id` with the surrender charge waived (the transfer being tax-free), driving that contract from `ACTIVE` to `SURRENDERED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and the administrative clock controls — return `200 OK`. All list and retrieval operations return `200 OK`. Request bodies, response bodies, and side effects are intentionally omitted from this table; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a product template | ContractAdmin |
| GET | `/products` | List products | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/products/{id}` | Retrieve a product | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/products/{id}/retire` | Retire a product | ContractAdmin |
| POST | `/contracts` | Create a contract in PENDING | ContractAdmin |
| GET | `/contracts` | List contracts | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}` | Retrieve a contract | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}/projection` | Forward-looking projected maturity value | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}/premiums` | List premiums on a contract | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}/withdrawals` | List withdrawals on a contract | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}/crediting-events` | List crediting events on a contract | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}/beneficiaries` | List beneficiaries on a contract | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}/sub-account-allocations` | List sub-account allocations on a contract | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}/index-segments` | List index segments on a contract | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}/annuitizations` | List annuitizations on a contract | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/contracts/{id}/death-claims` | List death claims on a contract | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/premiums` | Submit a premium (initial or subsequent) | ContractAdmin |
| GET | `/premiums` | List premiums | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/premiums/{id}` | Retrieve a premium | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/premiums/{id}/clear` | Clear a submitted premium | ContractAdmin |
| POST | `/premiums/{id}/reject` | Reject a submitted premium | ContractAdmin |
| POST | `/sub-account-allocations` | Add a variable-annuity division allocation | ContractAdmin |
| GET | `/sub-account-allocations/{id}` | Retrieve an allocation | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/index-segments` | Open an index crediting segment | ContractAdmin |
| GET | `/index-segments/{id}` | Retrieve an index segment | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/crediting-events` | Post a crediting event | CreditingOfficer |
| GET | `/crediting-events` | List crediting events | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| GET | `/crediting-events/{id}` | Retrieve a crediting event | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/withdrawals` | Request a partial or full withdrawal | ContractAdmin |
| GET | `/withdrawals/{id}` | Retrieve a withdrawal | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/withdrawals/{id}/settle` | Settle a requested withdrawal | ComplianceOfficer |
| POST | `/withdrawals/{id}/reject` | Reject a requested withdrawal | ComplianceOfficer |
| POST | `/beneficiaries` | Designate a beneficiary | ContractAdmin |
| GET | `/beneficiaries/{id}` | Retrieve a beneficiary | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/beneficiaries/{id}/revoke` | Revoke a beneficiary designation | ContractAdmin |
| POST | `/annuitizations` | Elect an annuitization payout option | ContractAdmin |
| GET | `/annuitizations/{id}` | Retrieve an annuitization | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/annuitizations/{id}/begin-payout` | Begin payout | ContractAdmin |
| POST | `/annuitizations/{id}/decline` | Decline an elected annuitization | ContractAdmin |
| POST | `/death-claims` | File a death claim | ContractAdmin |
| GET | `/death-claims/{id}` | Retrieve a death claim | ContractAdmin, CreditingOfficer, ComplianceOfficer |
| POST | `/death-claims/{id}/verify-identity` | Verify claimant identity | ComplianceOfficer |
| POST | `/death-claims/{id}/value-benefit` | Value the death benefit | ComplianceOfficer |
| POST | `/death-claims/{id}/fund` | Fund the death benefit | ComplianceOfficer |
| POST | `/death-claims/{id}/deny` | Deny a death claim | ComplianceOfficer |
| POST | `/exchanges-1035` | Create a 1035 exchange in DRAFT | ContractAdmin |
| GET | `/exchanges-1035` | List 1035 exchanges | ContractAdmin, ComplianceOfficer |
| GET | `/exchanges-1035/{id}` | Retrieve a 1035 exchange | ContractAdmin, ComplianceOfficer |
| POST | `/exchanges-1035/{id}/submit` | Submit a draft/revised exchange | ContractAdmin |
| POST | `/exchanges-1035/{id}/request-revision` | Return a submitted exchange for correction | ComplianceOfficer |
| POST | `/exchanges-1035/{id}/approve` | Approve a submitted exchange | ComplianceOfficer |
| POST | `/exchanges-1035/{id}/reject` | Reject a submitted exchange | ComplianceOfficer |
| POST | `/exchanges-1035/{id}/settle` | Settle an approved exchange | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the server wall clock (test-driving) | ContractAdmin |
| POST | `/_clock/roll_anniversary` | Roll a contract to its next anniversary | ContractAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_STALE_EXCHANGE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_CONTRACT_FROZEN` | 409 |
| `ERR_CREDITING_KIND_MISMATCH` | 422 |
| `ERR_ALLOCATION_INCOMPLETE` | 409 |
| `ERR_BENEFICIARY_SHARES_INCOMPLETE` | 409 |
| `ERR_FUTURE_DATE_OF_DEATH` | 422 |
| `ERR_PAYOUT_OPTION_ARITY` | 422 |
| `ERR_BELOW_MINIMUM_PREMIUM` | 422 |
| `ERR_INSUFFICIENT_ACCUMULATION` | 409 |
| `ERR_INVALID_COST_BASIS` | 422 |
| `ERR_SEGMENT_TERM_OVERLAP` | 409 |
| `ERR_CREDIT_PERIOD_OVERLAP` | 409 |
