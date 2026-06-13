# Crop Insurance RMA API — Product Requirements Document

## 1. Introduction

This document specifies the Crop Insurance (USDA RMA) Administration API, a back-office system for administering Multi-Peril Crop Insurance under the actuarial framework published by the USDA Risk Management Agency. The system models the full chain from configuring per-crop, per-county actuarial parameters, through a producer's election of yield or revenue coverage, the reporting of planted and prevented acreage, and finally the adjustment and disbursement of loss and prevented-planting indemnities. Throughout, it maintains a conserved premium ledger — every dollar of premium is split between the federal subsidy share and the producer's own share — and an agent-commission ledger that mirrors the elections those agents sold.

Two design tensions drive the bulk of the business logic. First, the same physical loss yields a *different* indemnity depending on whether the producer elected yield protection or one of the two revenue-protection variants, so the platform carries a dual-variant indemnity calculation that must agree with RMA's published methodology to the cent. Second, the program enforces a strict separation of responsibilities: the agent who sells a policy may never be the loss adjuster who approves a claim against it, deadlines for acreage reporting and planting are hard gates measured against a server-controlled clock, and concurrent edits to a policy's premium ledger or a unit's acreage record are rejected when the writer's view of the resource has gone stale. The remainder of this document defines the global contract every endpoint honors (§2), the domain workflows and their calculations (§3), the endpoint surface (§4), and the catalogue of error identifiers (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles: `RmaAdmin`, `Agent`, and `LossAdjuster`. When a well-authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN`.

The `RmaAdmin` role is the USDA/RMA operator. It manages commodity programs (creating them, opening them for sales, closing them, and publishing the discovered harvest price), disburses approved indemnities, and sets the server clock. When `X-User-Role` is `RmaAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

The `Agent` role is the selling agent of record. An agent creates policies, coverage elections, and units, files acreage reports, and files notices of loss and prevented-planting claims. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent` entity; ownership and segregation checks on any resource that references an `Agent` (for example a policy's selling `agent_id`, or a loss claim's `assigned_adjuster_id`) compare that foreign-key field to `X-User-ID`.

The `LossAdjuster` role is the independent adjuster who reviews, returns, approves, and denies loss and prevented-planting claims, and who is deliberately segregated from the selling agent. When `X-User-Role` is `LossAdjuster`, `X-User-ID` is likewise the `id` of the acting `Agent` entity (adjusters are persisted as `Agent` records carrying a `role_kind` of `ADJUSTING`); the assignment and segregation checks compare the claim's `assigned_adjuster_id` and the policy's selling `agent_id` against `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a particular endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses always carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Audit Trail

Most resources in this system — `CommodityProgram`, `Policy`, `CoverageElection`, `Unit`, `AcreageReport`, `LossClaim`, `PreventedPlantingClaim`, and `AgentCommission` — carry a uniform set of system-managed fields. Each has an `id`, a server-minted UUID with no type prefix. Each has a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource first came into being, and an `updated_at` of the same format recording the most recent mutation. Each also has a `version`, an integer that begins at 1 on creation and increments by one on every mutation; this integer is the basis for the optimistic concurrency control described in §2.7.

The two identity entities are the exception. A `Producer` and an `Agent` carry only an `id` and a `created_at`; they have neither an `updated_at` nor a `version`, because they are registered once and not subsequently mutated through this API.

### 2.5. Hierarchical Consistency and Automatic Propagation

The platform keeps a producer's policy, its elections, units, reports, and claims in mutual agreement without requiring the client to touch each level explicitly. Many state changes therefore *bubble up* or *cascade down* automatically. When the acreage report that finally completes the last outstanding unit under an election is accepted, the system promotes that election on its own; when a policy is cancelled, the void propagates downward through its elections to their units and commission entries. Whenever the server mutates a resource as part of such propagation — including recomputing a derived ledger field — that resource's `updated_at` is refreshed and its `version` is incremented, exactly as if the client had mutated it directly. Each cascade hop is its own mutation with its own version bump on the affected resource. The precise triggers, target states, and recomputations for each cascade are specified in the §3 workflows that own them.

### 2.6. Monetary Precision, Acreage, and Rounding Discipline

All money in the system is stored and returned as integer cents — fields whose names end in `_cents` are always whole-number integers, never fractional. Wherever a calculation produces cents, the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two integers rounds up to the larger). The order in which rounding is applied is itself part of the contract and is stated alongside each calculation in §3, because premium and indemnity figures are built by rounding a per-acre amount to whole cents *before* multiplying by acreage, rather than rounding only at the end. Yield figures expressed in bushels per acre — the `yield_guarantee_bu` in particular — are rounded to two decimal places, again half-up. Rate and factor fields (such as `base_premium_rate`, `subsidy_factor`, `commission_rate`, and `pp_coverage_factor`) preserve their full input or table precision and are not rounded for storage.

### 2.7. Optimistic Concurrency Control on Guarded Writes

Two write operations are guarded by optimistic concurrency control, and only these two. The first is the filing of an acreage report: a request to file an acreage report must carry `expected_unit_version`, holding the client's last observed `version` of the target `Unit`. If that value does not equal the unit's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the serialization point for the one-accepted-report-per-unit rule — once a prior writer has had a report accepted on the unit, the unit's `version` has advanced, so a second writer working from a stale view is turned away rather than silently superseding work it never saw. The second guarded write is the voiding of a coverage election: that request must carry `expected_policy_version`, holding the client's last observed `version` of the owning `Policy`. If the policy's `version` has advanced since the client read it — because another election was voided, or the policy was activated, recomputing the premium ledger — the void is rejected with `ERR_STALE_VERSION` (HTTP 412), since the caller's view of the premium ledger is stale.

No other endpoint accepts or requires a version field. An endpoint that is not one of these two never takes an `expected_unit_version` or `expected_policy_version` input and performs no concurrency check.

### 2.8. Nested-Path Resolution and Referential Existence

Several read endpoints address a resource through a parent in the path — for example listing the coverage elections under a policy, the units under an election, or the acreage reports under a unit. The path identifiers are validated left to right: the parent named earlier in the path is resolved first, and if it does not exist the request fails with `ERR_NOT_FOUND` before any later segment is considered. The same existence discipline applies to foreign keys carried in a request body: after path segments resolve, each referenced resource id in the body (such as a `policy_id`, `commodity_program_id`, `coverage_election_id`, `unit_id`, `producer_id`, `agent_id`, or `assigned_adjuster_id`) is checked for existence, and a dangling reference yields `ERR_NOT_FOUND`.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of every referenced path and body resource (`ERR_NOT_FOUND`), then well-formedness of the request body — required fields present, enum values legal, `coverage_level` drawn from the allowed set, and numeric fields positive where positivity is required (`ERR_INVALID_REQUEST`). Only after those four gates does the optimistic concurrency check run (`ERR_STALE_VERSION`), followed by the state-machine check that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Domain-specific business rules — segregation of duties, adjuster assignment, harvest-price availability, program openness, deadline gating, and acreage arithmetic — are evaluated after those structural gates. The specific business rule for each operation, and the error it raises, is given with that operation's narrative in §3.

### 2.10. The Server Clock

Temporal gates in this system — whether an acreage report arrives before its deadline, and whether a planting date counts as late — are measured against a single server-held notion of "now" in UTC, rather than the wall clock. An administrative capability sets that current instant from a supplied `to_iso8601` value, allowing deterministic control of every temporal check. Until set, the server uses its own current time; once set, all deadline and late-planting comparisons use the supplied instant.

## 3. Business Logic & Workflows

### 3.1. Configuring Commodity Programs

Everything begins with a **commodity program**, the actuarial parameter set for one crop in one county for one reinsurance year. An `RmaAdmin` creates a program by supplying the `crop_code` (for example `CORN`, `SOYBEANS`, or `WHEAT`), the `county_code` (a FIPS-style county code such as `19153`), the `crop_year` (which must be at least 2000), the `projected_price` per bushel (which must be greater than zero, established at sales close), the `base_premium_rate` applied to dollar liability (which must lie strictly between 0 and 1), the `pp_coverage_factor` used for prevented-planting payouts (which must be greater than 0 and at most 1), the `final_planting_date`, and the `acreage_reporting_deadline`. A newly created program begins with its `status` field set to `DRAFT` and `harvest_price_published` set to false; its `harvest_price` is null until discovery, and the program is not yet sellable. Every resource that has a lifecycle exposes its current state through a `status` field carrying one of the enumerated values described for that resource.

An `RmaAdmin` opens a program for sales, moving it from `DRAFT` to `OPEN`. Opening is permitted only when the `projected_price` is set and greater than zero and when both the `final_planting_date` and the `acreage_reporting_deadline` are set; on success the program's `version` increments by one, and coverage elections may from then on reference it. Later, the same administrator closes a program, moving it from `OPEN` to `CLOSED`, which blocks any further new elections against it; closing increments the program's `version` by one. A program cannot be closed while any coverage election that references it is still in `ELECTED` status — that attempt is rejected with `ERR_PROGRAM_HAS_OPEN_ELECTIONS`. `CLOSED` is the terminal state of a program.

Harvest-price discovery is a distinct administrative event. When the marketplace harvest price becomes known, an `RmaAdmin` publishes it by supplying `harvest_price`; this records the value on the program, sets `harvest_price_published` to true, and increments the program's `version` by one. This event is a precondition for adjusting revenue-protection losses, as §3.6 describes.

### 3.2. Policies, Producers, and Selling Agents

Before a policy exists, its two human parties must be registered. A `Producer` — the insured — is registered with a `name` and a `tax_id`, and may be created by either an `RmaAdmin` or an `Agent`. An `Agent` record — which represents both selling agents and loss adjusters for audit purposes — is registered by an `RmaAdmin` with a `name`, a `license_number`, and a `role_kind` of either `SELLING` or `ADJUSTING`.

An `Agent` then creates a **policy** for a producer by supplying the `producer_id`, the selling `agent_id`, and the `crop_year` the policy covers. A new policy starts in `DRAFT` status with all of its ledger fields at zero: `total_premium_cents`, `producer_premium_cents`, `subsidy_cents`, `total_indemnity_cents`, and `total_insured_acres`. Those fields are never written by the client; they are derived sums maintained by the system as elections, units, and claims accrue beneath the policy.

Activation moves the policy from `DRAFT` to `ACTIVE` and is performed by an `Agent`. Activation is permitted only when at least one coverage election under the policy is in `ELECTED` status; otherwise it is rejected with `ERR_POLICY_HAS_NO_ELECTIONS`. Activating earns commissions — for each `ELECTED` election the system creates or finalizes an `AgentCommission` in `EARNED` status, computed as §3.8 describes — and increments the policy's `version` by one. Once active, the policy is locked in for acreage reporting and loss adjustment.

Cancellation is the policy's terminal transition, available to an `Agent`, moving it from `ACTIVE` to `CANCELLED`. A policy may not be cancelled while any loss claim or prevented-planting claim beneath it is in `UNDER_REVIEW` or `APPROVED`; that attempt is rejected with `ERR_POLICY_HAS_OPEN_CLAIMS`. When cancellation does proceed, it triggers a two-hop cascade: every coverage election under the policy that is not already `VOID` transitions to `VOID`; then each voided election in turn voids its non-`SETTLED` units and claws back the election's `AgentCommission`. After the cascade, the policy's premium ledger — `total_premium_cents`, `producer_premium_cents`, and `subsidy_cents` — is recomputed with the voided elections dropped, and the policy's `version` increments by one.

The set of coverage elections under a policy can be listed through that policy, as can — indirectly — its other descendants, and a single policy can be fetched to read back its computed ledger fields.

### 3.3. Electing Coverage: Plan, Level, and the Guarantee

A **coverage election** records a producer's choice of protection for one commodity under a policy. An `Agent` creates it by supplying the `policy_id`, the `commodity_program_id` whose actuarial parameters apply, the `plan_type`, the `aph_yield` (the Actual Production History yield in bushels per acre, which must be greater than zero), and the `coverage_level`. The `plan_type` is one of `YP` (yield protection), `RP` (revenue protection), or `RP_HPE` (revenue protection with the harvest-price exclusion). The `coverage_level` must be exactly one of `0.50`, `0.55`, `0.60`, `0.65`, `0.70`, `0.75`, `0.80`, or `0.85`; any other value is malformed input. The referenced commodity program must be in `OPEN` status at creation time — electing against a program that is not open is rejected with `ERR_PROGRAM_NOT_OPEN`. A new election starts in `ELECTED` status.

At creation the system computes the election's guarantee from the program's projected price. The `yield_guarantee_bu` — the guaranteed yield in bushels per acre — is the product of the `aph_yield` and the `coverage_level`, rounded to two decimal places. The `dollar_liability_per_acre_cents` is then the `yield_guarantee_bu` multiplied by the program's `projected_price`, that product multiplied by 100 to convert dollars to cents, and the whole rounded to a whole number of cents. Liability always uses the projected price, never the harvest price, because the harvest price is unknown at election time. The election's `subsidy_factor` is also fixed at this moment by looking up the `coverage_level` in the federal subsidy table (see §3.4). Until units are added, the election's `total_premium_cents` is zero.

An election that has not yet accumulated any reported acreage can be voided directly by an `Agent`, moving it from `ELECTED` to `VOID`. A direct void is permitted only when no unit under the election has an `ACCEPTED` acreage report; if any unit is already reported, the void is rejected with `ERR_ELECTION_ALREADY_REPORTED`. Because voiding rewrites the owning policy's premium ledger, this write is guarded by optimistic concurrency: the request must carry `expected_policy_version` matching the owning policy's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` as described in §2.7. When a void succeeds — whether requested directly or reached as a cascade hop from a policy cancellation — its units that are still `PENDING` transition to `VOID`, the election's `AgentCommission` (if `EARNED`) transitions to `CLAWED_BACK` with its `clawback_cents` set equal to its `commission_cents`, the owning policy's `total_premium_cents`, `producer_premium_cents`, and `subsidy_cents` are recomputed with this election excluded, and the owning policy's `version` increments by one. An election that has been indemnified (`INDEMNIFIED`) or voided (`VOID`) is terminal.

### 3.4. Premium, Subsidy, and the Conserved Ledger

Premium accrues unit by unit. The per-acre premium for an election is built from three factors — the election's `dollar_liability_per_acre_cents`, the program's `base_premium_rate`, and a plan loading multiplier that depends on `plan_type`: the multiplier is 1.00 for `YP`, 1.15 for `RP`, and 1.08 for `RP_HPE`. The per-acre premium in cents is the product of those three, rounded to a whole number of cents. This rounding to whole cents happens *first*, before any acreage is applied. Each unit's premium contribution is then that rounded per-acre figure multiplied by the unit's `acres` and its `share`, again rounded to a whole number of cents. The election's `total_premium_cents` is the sum of those per-unit contributions across every unit under the election whose status is `PENDING`, `REPORTED`, or `ACTIVE`; units that are `VOID` or `SETTLED` are excluded. Because each unit is rounded before summing, the order is round-per-unit-then-sum, never sum-then-round. The `total_premium_cents` is recomputed every time the election is created and every time a unit is added.

From the premium, the system splits the federal subsidy from the producer's share. The `subsidy_factor` is looked up by exact `coverage_level` key in the federal subsidy table, with no interpolation between levels: a level of `0.50` maps to 0.67; `0.55` and `0.60` both map to 0.64; `0.65` and `0.70` both map to 0.59; `0.75` maps to 0.55; `0.80` maps to 0.48; and `0.85` maps to 0.38. The election's `subsidy_cents` is the `total_premium_cents` multiplied by the `subsidy_factor`, rounded to a whole number of cents. The election's `producer_premium_cents` is then simply the `total_premium_cents` minus the `subsidy_cents` — derived by subtraction with no independent rounding, so that the subsidy share and the producer share always sum back exactly to the total. This recompute runs whenever the premium itself is recomputed.

The policy's ledger is the roll-up of its live elections. A policy's `total_premium_cents` is the sum of `total_premium_cents` across its elections in `ELECTED`, `REPORTED`, or `INDEMNIFIED` status, and its `producer_premium_cents` and `subsidy_cents` are the corresponding sums of the elections' producer and subsidy shares over that same set. The policy's `subsidy_cents` therefore also equals its `total_premium_cents` minus its `producer_premium_cents`, reflecting the federal subsidy share. Voided elections drop out of all three sums, which is precisely why voiding and cancellation force a ledger recompute.

### 3.5. Acreage Reporting and the Unit Lifecycle

A **unit** is an insurable acreage block under an election. An `Agent` adds a unit by supplying the `coverage_election_id`, a producer-assigned `unit_number` label (such as `0001-0001`), the insured `acres` (which must be greater than zero), and the producer's `share` of the unit (a fraction greater than zero and at most 1). A new unit begins in `PENDING` status with `planted_acres` and `prevented_acres` both at zero. Adding a unit recomputes the election's `total_premium_cents` and its subsidy split, and recomputes the owning policy's premium ledger, all per §3.4.

Acreage is reported by filing an **acreage report** against a unit. An `Agent` files it by supplying the `unit_id`, the `planted_acres` actually planted (which must be at least zero), the `prevented_acres` prevented from planting (which must be at least zero), an optional `planting_date` (null if the unit was fully prevented), and the `expected_unit_version` for the concurrency check of §2.7. Filing is gated on time: it is rejected with `ERR_ACREAGE_DEADLINE_PASSED` if the server's current clock is strictly after the program's `acreage_reporting_deadline` — that is, filing is allowed only while now is at or before the deadline. It is also gated on arithmetic: the sum of `planted_acres` and `prevented_acres` may not exceed the unit's `acres`, and a sum that exceeds the insured acreage is rejected with `ERR_ACREAGE_OVER_REPORTED`. The unit's owning election must be in `ELECTED` status for a report to move the unit forward.

On acceptance, several things happen at once. Any prior `ACCEPTED` report on the same unit transitions to `SUPERSEDED` so that only one report is ever `ACCEPTED` per unit, and the new report becomes `ACCEPTED` (reports otherwise begin life `FILED`). The report's `late_planted` flag is computed as true when the `planting_date` is strictly after the program's `final_planting_date`, and false otherwise. The unit's `planted_acres` and `prevented_acres` are set from the accepted report, and the unit transitions from `PENDING` to `REPORTED`. If accepting this report means every sibling unit under the election is now `REPORTED`, the election bubbles up from `ELECTED` to `REPORTED`, signaling it is eligible for loss adjustment. Finally the owning policy's `total_insured_acres` is recomputed — it is the sum of `acres` across the policy's units that are in `REPORTED` or `ACTIVE` status — and the unit's `version` increments by one.

A unit's later lifecycle is driven by claims. When the first loss claim or prevented-planting claim is filed against a `REPORTED` unit, the unit advances to `ACTIVE`, flagging it as in adjustment. When a claim on the unit reaches a final outcome — approved or denied — and no other claim on that unit is still in `DRAFT` or `UNDER_REVIEW`, the unit transitions from `ACTIVE` to `SETTLED`, closing it to further claims. A unit that is voided as a cascade from its election's void moves from `PENDING` to `VOID` and triggers a recompute of the owning policy's `total_insured_acres`. `SETTLED` and `VOID` are the unit's terminal states.

### 3.6. Notices of Loss and the Adjustment Workflow

A **loss claim** is the notice-of-loss artifact and carries its own review lifecycle. An `Agent` files one by supplying the `unit_id`, the `harvest_date` (the reported harvest or appraisal date), the `production_to_count_bu` (the total bushels produced or appraised on the whole unit, which must be at least zero, not a per-acre figure), and the `assigned_adjuster_id` naming the `Agent` record of the loss adjuster assigned at intake. A new claim begins in `DRAFT` with `indemnity_cents` at zero and `revision_count` at zero.

The agent submits the claim for review, moving it from `DRAFT` to `UNDER_REVIEW`. Submission requires that the unit be `REPORTED` or `ACTIVE`; submitting against a unit not yet reported is rejected with `ERR_UNIT_NOT_REPORTED`. For revenue plans — that is, an election whose `plan_type` is `RP` or `RP_HPE` — submission additionally requires that the commodity program's harvest price has been published; otherwise it is rejected with `ERR_HARVEST_PRICE_UNAVAILABLE`. On submission, a unit that was `REPORTED` advances to `ACTIVE`.

The adjustment loop itself is the segregated, branching heart of the system. The assigned adjuster may **return** the claim for rework, moving it from `UNDER_REVIEW` back to `DRAFT` and incrementing its `revision_count` by one; the claim may then be resubmitted, so a claim can cycle through `DRAFT → UNDER_REVIEW → DRAFT` any number of times. Returning requires that the acting `LossAdjuster`'s identity match the claim's `assigned_adjuster_id`; an adjuster who is not the assigned one is rejected with `ERR_ADJUSTER_NOT_ASSIGNED`. From `UNDER_REVIEW` the adjuster may instead **approve** or **deny** the claim. Both approval and denial enforce two safety rules in turn: the acting adjuster must be the claim's `assigned_adjuster_id` (else `ERR_ADJUSTER_NOT_ASSIGNED`), and — the segregation-of-duties guarantee — the acting adjuster must *not* be the selling `agent_id` of the unit's policy (else `ERR_SEGREGATION_OF_DUTIES`); for these two checks the assigned-adjuster check is evaluated before the segregation check.

Approval moves the claim from `UNDER_REVIEW` to `APPROVED`, computes and sets its `indemnity_cents` by the methodology of §3.7 (which is required to be at least zero), then cascades: the owning election bubbles from `REPORTED` to `INDEMNIFIED`, the approved `indemnity_cents` is added into the policy's `total_indemnity_cents`, and the unit transitions to `SETTLED` if no other open claim remains on it. Denial moves the claim from `UNDER_REVIEW` to `DENIED`, leaving `indemnity_cents` at zero, and likewise settles the unit if no other open claim remains. Finally, an `RmaAdmin` pays an approved claim, moving it from `APPROVED` to `PAID`, which marks the indemnity disbursed. `DENIED` and `PAID` are the claim's terminal states.

### 3.7. The Dual-Variant Indemnity Calculation

When a loss claim is approved, its indemnity is computed from the unit's measured production, and the *method* depends on the election's `plan_type`. In all variants, the guaranteed yield per acre is the election's `yield_guarantee_bu`, the insured acreage is the unit's `acres`, and the producer's interest is the unit's `share`. The production actually made per acre is the claim's `production_to_count_bu` divided by the unit's `acres`.

For a yield-protection election (`plan_type` of `YP`), the loss is measured purely in bushels and priced at the projected price; the harvest price is ignored entirely. The per-acre indemnity is the shortfall of guaranteed yield below production made — that is, the guaranteed yield per acre minus the production per acre, but never less than zero — multiplied by the program's `projected_price`.

For a revenue-protection election, the loss is measured in revenue rather than bushels, which is why the same physical shortfall can produce a larger indemnity than the yield-protection path. The revenue guarantee per acre is the guaranteed yield per acre multiplied by a revenue price, and the calculated revenue per acre is the production per acre multiplied by the program's `harvest_price`. The per-acre indemnity is the revenue guarantee per acre minus the calculated revenue per acre, but never less than zero. The two revenue variants differ only in the revenue price used for the guarantee: for `RP`, the revenue price is the greater of the projected price and the harvest price (so the producer captures harvest-price upside); for `RP_HPE`, the revenue price is the projected price alone, excluding harvest-price upside. In both revenue variants the calculated revenue still uses the harvest price.

Whichever variant applies, the claim's `indemnity_cents` is the per-acre indemnity multiplied by the unit's `acres`, multiplied by the unit's `share`, multiplied by 100 to convert to cents, and the final figure rounded to a whole number of cents. All per-acre arithmetic is carried through before that single final rounding.

### 3.8. Prevented Planting and Agent Commissions

A **prevented-planting claim** is a separate indemnity path for acreage that could not be planted at all. An `Agent` files one by supplying the `unit_id`, the `claimed_prevented_acres` (which must be greater than zero), and the `cause`, one of `EXCESS_MOISTURE`, `DROUGHT`, `FLOOD`, or `OTHER`. It begins in `DRAFT` with `pp_indemnity_cents` at zero. The agent submits it, moving it from `DRAFT` to `UNDER_REVIEW`, which requires both that the `claimed_prevented_acres` not exceed the unit's reported `prevented_acres` (else `ERR_PP_ACRES_EXCEED_REPORTED`) and that the unit be `REPORTED` or `ACTIVE` (else `ERR_UNIT_NOT_REPORTED`); a `REPORTED` unit advances to `ACTIVE` on submission. A `LossAdjuster` then approves or denies it. Both approval and denial require that the acting adjuster not be the policy's selling `agent_id`, enforcing segregation of duties with `ERR_SEGREGATION_OF_DUTIES`. Approval moves the claim from `UNDER_REVIEW` to `APPROVED`, sets `pp_indemnity_cents`, cascades the owning election from `REPORTED` to `INDEMNIFIED`, adds `pp_indemnity_cents` into the policy's `total_indemnity_cents`, and settles the unit if no other open claim remains. Denial moves it from `UNDER_REVIEW` to `DENIED`, leaving `pp_indemnity_cents` at zero, and likewise settles the unit if no other open claim remains. `APPROVED` and `DENIED` are this claim's terminal states.

The prevented-planting indemnity is computed at approval from the election's liability and the program's prevented-planting factor. The prevented-planting indemnity per acre in cents is the election's `dollar_liability_per_acre_cents` multiplied by the program's `pp_coverage_factor`, rounded to a whole number of cents; the per-acre figure is rounded first. The claim's `pp_indemnity_cents` is then that rounded per-acre amount multiplied by the `claimed_prevented_acres` and the unit's `share`, rounded again to a whole number of cents.

Commissions track the elections an agent sold. An `AgentCommission` ties an `agent_id` to a `coverage_election_id`, and is earned when the policy activates. Its `commission_rate` is selected by tier from the election's finalized `total_premium_cents` — and because the tier is keyed on the very total it scales, the premium total must be finalized before the tier is chosen. If the total premium is below 500000 cents (five thousand dollars), the rate is 0.10; if it is at least 500000 cents and at most 1000000 cents (five thousand through ten thousand dollars, inclusive), the rate is 0.08; if it is above 1000000 cents (more than ten thousand dollars), the rate is 0.06. The `commission_cents` is the election's `total_premium_cents` multiplied by the selected `commission_rate`, rounded to a whole number of cents. A commission is created `EARNED` with `clawback_cents` at zero. When the underlying election is voided, the commission flips to `CLAWED_BACK` and its `clawback_cents` is set equal to its `commission_cents`, reversing the earned amount. Commission entries can be read individually or listed by agent or by election.

## 4. Endpoint Definitions

Operations that bring a brand-new resource into existence return `201 Created`; operations that drive a state transition, recompute a ledger, or otherwise modify an existing resource return `200 OK`. All list and fetch operations return `200 OK`. The request body, response body, and side effects of each endpoint are governed by the narratives in §3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/producers` | Register a producer (insured) | RmaAdmin, Agent |
| POST | `/agents` | Register a selling agent or loss adjuster | RmaAdmin |
| POST | `/commodity-programs` | Create an actuarial commodity program | RmaAdmin |
| GET | `/commodity-programs/{id}` | Fetch a commodity program | RmaAdmin, Agent, LossAdjuster |
| GET | `/commodity-programs` | List commodity programs | RmaAdmin, Agent, LossAdjuster |
| POST | `/commodity-programs/{id}/open` | Open a program for sales | RmaAdmin |
| POST | `/commodity-programs/{id}/close` | Close a program to new elections | RmaAdmin |
| POST | `/commodity-programs/{id}/publish-harvest-price` | Publish the discovered harvest price | RmaAdmin |
| POST | `/policies` | Create a policy for a producer | Agent |
| GET | `/policies/{id}` | Fetch a policy with computed ledger fields | RmaAdmin, Agent, LossAdjuster |
| GET | `/policies` | List policies | RmaAdmin, Agent, LossAdjuster |
| GET | `/policies/{id}/coverage-elections` | List coverage elections under a policy | RmaAdmin, Agent, LossAdjuster |
| POST | `/policies/{id}/activate` | Activate a policy; earns commissions | Agent |
| POST | `/policies/{id}/cancel` | Cancel a policy; cascades void + clawback | Agent |
| POST | `/coverage-elections` | Create a coverage election under a policy | Agent |
| GET | `/coverage-elections/{id}` | Fetch a coverage election | RmaAdmin, Agent, LossAdjuster |
| GET | `/coverage-elections` | List coverage elections | RmaAdmin, Agent, LossAdjuster |
| GET | `/coverage-elections/{id}/units` | List units under an election | RmaAdmin, Agent, LossAdjuster |
| POST | `/coverage-elections/{id}/void` | Void an election (OCC on owning policy) | Agent |
| POST | `/units` | Add an insurable unit to an election | Agent |
| GET | `/units/{id}` | Fetch a unit | RmaAdmin, Agent, LossAdjuster |
| GET | `/units` | List units | RmaAdmin, Agent, LossAdjuster |
| GET | `/units/{id}/acreage-reports` | List acreage reports for a unit | RmaAdmin, Agent, LossAdjuster |
| POST | `/acreage-reports` | File an acreage report (OCC on unit) | Agent |
| GET | `/acreage-reports/{id}` | Fetch an acreage report | RmaAdmin, Agent, LossAdjuster |
| GET | `/acreage-reports` | List acreage reports | RmaAdmin, Agent, LossAdjuster |
| POST | `/loss-claims` | File a notice of loss against a unit | Agent |
| GET | `/loss-claims/{id}` | Fetch a loss claim | RmaAdmin, Agent, LossAdjuster |
| GET | `/loss-claims` | List loss claims | RmaAdmin, Agent, LossAdjuster |
| POST | `/loss-claims/{id}/submit` | Submit a loss claim for review | Agent |
| POST | `/loss-claims/{id}/return` | Return a claim for rework | LossAdjuster |
| POST | `/loss-claims/{id}/approve` | Approve; computes indemnity, cascades | LossAdjuster |
| POST | `/loss-claims/{id}/deny` | Deny the claim | LossAdjuster |
| POST | `/loss-claims/{id}/pay` | Disburse an approved indemnity | RmaAdmin |
| POST | `/prevented-planting-claims` | File a prevented-planting claim | Agent |
| GET | `/prevented-planting-claims/{id}` | Fetch a prevented-planting claim | RmaAdmin, Agent, LossAdjuster |
| GET | `/prevented-planting-claims` | List prevented-planting claims | RmaAdmin, Agent, LossAdjuster |
| POST | `/prevented-planting-claims/{id}/submit` | Submit a prevented-planting claim for review | Agent |
| POST | `/prevented-planting-claims/{id}/approve` | Approve; computes pp indemnity, cascades | LossAdjuster |
| POST | `/prevented-planting-claims/{id}/deny` | Deny the prevented-planting claim | LossAdjuster |
| GET | `/agent-commissions/{id}` | Fetch a commission ledger entry | RmaAdmin, Agent |
| GET | `/agent-commissions` | List commissions | RmaAdmin, Agent |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock | RmaAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_ADJUSTER_NOT_ASSIGNED` | 409 |
| `ERR_HARVEST_PRICE_UNAVAILABLE` | 409 |
| `ERR_PROGRAM_NOT_OPEN` | 409 |
| `ERR_PROGRAM_HAS_OPEN_ELECTIONS` | 409 |
| `ERR_ACREAGE_DEADLINE_PASSED` | 409 |
| `ERR_ACREAGE_OVER_REPORTED` | 422 |
| `ERR_PP_ACRES_EXCEED_REPORTED` | 422 |
| `ERR_ELECTION_ALREADY_REPORTED` | 409 |
| `ERR_POLICY_HAS_NO_ELECTIONS` | 409 |
| `ERR_POLICY_HAS_OPEN_CLAIMS` | 409 |
| `ERR_UNIT_NOT_REPORTED` | 409 |
