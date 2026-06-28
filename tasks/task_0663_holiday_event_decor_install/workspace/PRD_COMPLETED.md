# Holiday Event Decor Install API — Product Requirements Document

## 1. Introduction

Commercial holiday and event décor is a seasonal logistics business with a long memory. A single shopping-center account or homeowners' association may sign a recurring contract years before its trees, wreaths, garlands, and lighting are ever unpacked, store its décor in a numbered warehouse bay through the off-season, and renew the same arrangement season after season at an escalated rate. This API is the system of record for that full arc: it captures the design and quoting of a season's décor, schedules the crews that install, refresh, and take it down, tracks the inventory those crews draw against, books off-season storage, settles damage discovered during takedown, and offers the contract for renewal when the season closes.

The platform serves four cooperating constituencies. Account managers own the commercial relationship — they open accounts, draft contracts, author design proposals, bill completed work, and extend renewal offers. Field supervisors own operations — crews, the work orders those crews execute as routed visits, warehouse storage, and the damage-and-restock cycle. A client's own contact signs contracts and decides proposals and renewals on the client's behalf. A platform operator maintains the décor catalog, fulfills restock orders, and controls the logical clock that governs every early-bird and offer-expiry deadline. The sections below specify the global contracts every endpoint honors, then narrate the business workflows in detail, and finally enumerate the endpoint surface and error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API. Where a rule below references a numeric threshold, a state name, or a field name, that reference is authoritative and precise.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles, spelled precisely as `AccountManager`, `FieldSupervisor`, `ClientContact`, and `PlatformAdmin`. A request missing either header, or carrying an `X-User-Role` that is not one of these four, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A syntactically authenticated request whose role is not permitted to perform the targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Three of the four roles are opaque operator identities. When `X-User-Role` is `AccountManager`, `FieldSupervisor`, or `PlatformAdmin`, the accompanying `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. The fourth role is entity-backed: when `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`. Ownership is enforced for the client-signer's privileged actions — signing a contract, accepting or rejecting a proposal, and accepting or declining a renewal offer. For each such action the system resolves the `Client` that owns the targeted `Contract`, `DesignProposal`, or `RenewalOffer` (following `client_id` and the `contract_id` chain) and compares that owning client's `id` to `X-User-ID`. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific workflow says otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Resource Identity

Every resource the API mints carries a server-generated `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. The great majority of resources are mutable and additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every change, and an integer `version` that begins at 1 and increments by one on every mutation. The `Client`, `Contract`, `DesignProposal`, `ProposalLineItem`, `InventoryItem`, `Crew`, `WorkOrder`, `Visit`, `StorageLot`, `StorageBay`, `DamageReport`, `RestockOrder`, and `RenewalOffer` resources all carry the full `id` / `created_at` / `updated_at` / `version` quartet. There are no immutable, version-free resources in this domain; every entity participates in the standard mutation accounting.

Whenever a transition or computed-field refresh mutates a resource, the system refreshes that resource's `updated_at` and increments its `version`. This applies equally to derived fields: when signing a contract populates its fee fields, when accepting a proposal supersedes its siblings, or when fulfilling a restock order replenishes warehouse stock, the affected resources each see `updated_at` and `version` advance.

### 2.5. Nested Resource Retrieval and Reference Resolution

Many paths address a resource nested beneath one or more parents — for example a contract beneath a client, or a line item beneath a proposal. The system validates path identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource. A line-item request under a non-existent proposal therefore fails on the proposal before the line item is ever consulted.

Existence checking extends to the request body. On create and link operations, every foreign-key reference carried in the body — a `client_id`, `contract_id`, `proposal_id`, `inventory_item_id`, `storage_bay_id`, `crew_id`, `work_order_id`, or `damage_report_id` — must point to a resource that exists; a dangling body reference is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). Path-identifier existence (priority 4) is evaluated before body-reference existence (priority 5).

### 2.6. Request Validation and Evaluation Order

The system evaluates checks in a fixed priority order, so that earlier failures mask later ones. Authentication comes first: header presence and a known role (`ERR_UNAUTHENTICATED`, priority 1), then role permission for the operation (`ERR_FORBIDDEN_ROLE`, priority 2), then — for a `ClientContact` performing a sign, accept, reject, or decline — resource ownership (`ERR_NOT_RESOURCE_OWNER`, priority 3). Existence follows: path resources left to right (`ERR_NOT_FOUND`, priority 4), then body foreign keys (`ERR_REFERENCE_NOT_FOUND`, priority 5). Structural validation is next (priority 6): required body fields must be present and well-typed, every enum value must fall within its allowed set, and numeric constraints must hold — each `quantity` and `unit_count` at least 1, each bay `capacity_units` at least 1, and a storage lot's `released_on` strictly after its `stored_from`; any violation yields `ERR_INVALID_REQUEST` (HTTP 422). Optimistic-concurrency checking is priority 7 (`ERR_STALE_CONTRACT_VERSION`, described in §2.7). The general state-machine guard is priority 8: if the requested transition is not defined from the target's current state, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Only after all of these do the domain-specific business rules of priorities 9 through 16 run, in that numeric order. Where a single endpoint is guarded by several of these business rules, the lower-numbered priority is checked first and its error surfaces in preference to any higher-numbered rule.

### 2.7. Optimistic Concurrency on Contract-Targeting Writes

Two writes pivot on a `Contract`'s `version` and are therefore guarded by optimistic concurrency control. Each requires a non-optional `expected_contract_version` field in its request body, carrying the client's last observed `version` of the parent `Contract`. If `expected_contract_version` does not equal the contract's current `version`, the write is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), and the operation does not proceed.

The first guarded write is proposal acceptance. Accepting a `DesignProposal` advances the owning contract's `version` as it supersedes the sibling proposals; a subsequent acceptance that still carries the now-outdated `expected_contract_version` is rejected on the stale-version check rather than allowed to act on a contract it has not re-observed. The second guarded write is renewal-offer creation against a contract: the first creation advances the contract's `version` as it moves the contract into its renewal-offered posture, so a later creation carrying the stale `expected_contract_version` is likewise rejected. No other endpoint in the system takes a version field; endpoints not named here perform their mutations without an OCC check.

### 2.8. Monetary, Distance, and Percentage Precision

All money in this system is held and returned as integer cents — `install_fee_cents`, `storage_fee_cents`, `early_bird_discount_cents`, `total_amount_cents`, `custom_design_surcharge_cents`, `unit_install_cents`, `unit_replacement_cents`, `replacement_cost_cents`, `settlement_total_cents`, `provisional_price_cents`, and `final_price_cents` are all whole-cent integers. Wherever a calculation introduces a fraction of a cent — a bundle discount, an early-bird discount, a damage labor fee, or a renewal escalation — the result is rounded half-up to the nearest whole cent. The rounding rule is specified per calculation in §3, including the order in which rounding and summation interleave, because that order changes the result.

Route time is held in whole minutes. Per-leg drive time is computed from a distance in kilometers and rounded half-up to a whole minute. Crew utilization is held as a whole-number percentage, rounded half-up; utilization above 100 percent is meaningful — it signals overbooking — and is never capped at 100.

### 2.9. Hierarchical Consistency and Cascading Effects

Several operations mutate more than one resource. When a contract is cancelled, when a proposal is accepted, when a renewal offer is accepted or declined or expires, and when a restock-bearing damage report is settled, the primary transition triggers secondary effects on related resources. Each affected resource independently has its `updated_at` refreshed and its `version` incremented as part of the operation. The precise cascades are spelled out in the workflow narratives of §3; the governing principle here is that these multi-resource effects are atomic with the operation that triggers them and that no intermediate, partially-applied state is observable.

### 2.10. The Logical Clock

Early-bird eligibility and renewal-offer expiry are decided against a server-controlled logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-04-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to the host's wall clock. A platform operator may advance or reset the clock to a supplied instant; that supplied instant is provided as `to_iso8601`, and the clock-setting call stores that instant verbatim and returns it as the single field `current_utc` in its `data` object (rather than any standard resource). Every comparison in §3 that mentions "the current time," a deadline, or an expiry instant reads this logical clock.

## 3. Business Logic & Workflows

### 3.1. Accounts and the Contract Lifecycle

Everything begins with a `Client` — a commercial account, a homeowners' association, or an event customer. An account manager opens one by supplying its `legal_name`, its `account_type` (one of `COMMERCIAL`, `HOA`, or `EVENT`), a `contact_email` that doubles as the login identity of that client's signer, and a `site_address` naming the primary installation site. A new client is born with `status` set to `ACTIVE`; the account `status` has no further lifecycle transitions in this system and remains `ACTIVE`.

Against a client, an account manager drafts a `Contract`. The create supplies the `contract_type` (again one of `COMMERCIAL`, `HOA`, or `EVENT`), the `season_year` the contract covers, the `early_bird_deadline` instant on or before which signing unlocks the early-bird discount, and optionally a `custom_design_surcharge_cents` flat surcharge for bespoke work (defaulting to 0, and never negative). The `contract_type` must equal the owning client's `account_type`; a mismatch is rejected with `ERR_CONTRACT_TYPE_MISMATCH` (HTTP 422). A freshly created contract carries `status` `DRAFT`, a `renewed_from_contract_id` of null (it is set only when a contract is minted by accepting a renewal offer), and null values for its computed money fields `install_fee_cents`, `storage_fee_cents`, `early_bird_discount_cents`, and `total_amount_cents`. The contract references its account through `client_id`.

The contract then climbs a cyclic lifecycle through the states `DRAFT`, `PROPOSED`, `SIGNED`, `ACTIVE`, `RENEWAL_OFFERED`, `EXPIRED`, and `CANCELLED`, of which `EXPIRED` and `CANCELLED` are terminal. An account manager moves a contract from `DRAFT` to `PROPOSED`, which opens the client-review window; this is permitted only while the contract is `DRAFT` and at least one `DesignProposal` under it sits in `SUBMITTED` (a propose attempt with no `SUBMITTED` proposal is rejected with `ERR_INVALID_STATE`, HTTP 409). The client's contact then signs, advancing `PROPOSED` to `SIGNED`; signing requires the contract to be `PROPOSED` and that exactly one `DesignProposal` under it is in `ACCEPTED` (acceptance is a distinct prior step; a sign attempt where the count of `ACCEPTED` proposals is not exactly one is rejected with `ERR_INVALID_STATE`, HTTP 409). Signing is the moment all fee fields are computed — install fee, storage fee, early-bird discount, and contract total are all set in one transaction, as detailed in §3.3. An account manager then activates the contract, moving `SIGNED` to `ACTIVE`; activation requires only that the contract be `SIGNED`, and it is the point at which work orders may be scheduled against the contract. Each of these transitions increments the contract's `version` by one.

From `ACTIVE` a contract has two exits. The account manager may cancel it, moving `ACTIVE` to `CANCELLED`; cancellation is permitted only while the contract is `ACTIVE` and only when no work order for the contract sits in `schedule_status` `DISPATCHED`. Cancellation cascades: every non-terminal work order for the contract — that is, each one whose `schedule_status` is `UNSCHEDULED` or `SCHEDULED` — has its `schedule_status` set to `CANCELLED`, and every storage lot for the contract whose `status` is `RESERVED` or `STORED` is moved to `RELEASED`. The other exit from `ACTIVE`, into the renewal cycle, is covered in §3.7. Each transition out of a state, including those described later, increments the contract's `version`.

### 3.2. Designing the Décor: Proposals and Line Items

A décor design lives in a `DesignProposal`, a child of the contract. An account manager creates one by supplying its free-text `theme` and an optional `is_custom` flag (default false) that marks the proposal as containing bespoke custom-design work. A new proposal starts in `status` `DRAFT` with `total_unit_count` of 0, and references its parent through `contract_id`. Proposals move through `DRAFT`, `SUBMITTED`, `ACCEPTED`, `REJECTED`, and `SUPERSEDED`, of which `REJECTED` and `SUPERSEDED` are terminal.

Into a draft proposal an account manager adds one or more `ProposalLineItem` rows, each naming the catalog SKU being installed through `inventory_item_id`, a `quantity` of decor units (at least 1), and a `unit_install_cents` per-unit install labor-and-materials charge (zero or more). A line item carries `proposal_id` linking it back to its proposal.

The account manager submits the proposal, advancing `DRAFT` to `SUBMITTED`; submission requires the proposal to be `DRAFT` and to carry at least one line item, and it recomputes `total_unit_count` as the sum of `quantity` across the proposal's line items. The client's contact then decides the proposal. Acceptance advances `SUBMITTED` to `ACCEPTED` and requires the proposal to be `SUBMITTED`, the owning contract to be `PROPOSED`, and no sibling proposal under the same contract to already be `ACCEPTED`; if the contract is not `PROPOSED` or a sibling has already been accepted, the request is rejected with `ERR_PROPOSAL_ALREADY_DECIDED` (HTTP 409). Acceptance is the system's single-winner mechanism: at acceptance, every sibling `DesignProposal` under the same contract whose `status` is `DRAFT` or `SUBMITTED` is moved to `SUPERSEDED`. Acceptance also advances the parent contract's `version` (this is what the OCC guard of §2.7 protects) in addition to the proposal's own `version`. Alternatively the contact may reject, advancing `SUBMITTED` to `REJECTED`, which requires only that the proposal be `SUBMITTED`. Each proposal transition increments the proposal's `version`.

Because acceptance is guarded by optimistic concurrency, the contact's accept call must carry `expected_contract_version` equal to the contract's current `version`; if a prior sibling acceptance has already advanced that `version`, the second accept carrying the stale value is turned away with `ERR_STALE_CONTRACT_VERSION` before the supersede logic runs.

### 3.3. Pricing a Signed Contract

Signing is the pricing event. In one transaction the system computes four figures over the contract's single `ACCEPTED` proposal and its stored décor, in a pinned order: first the install fee, then the storage fee, then the early-bird discount and the final total.

**Install fee.** The install fee is summed over the line items of the contract's one `ACCEPTED` proposal; proposals in `SUPERSEDED` or `REJECTED` are excluded. First the system totals the units across those line items (this equals the proposal's `total_unit_count`) and selects a bundle-discount rate from the total: no discount when the total is below 50 units; 5 percent when the total is at least 50 but below 100; 10 percent when the total is at least 100 but below 200; and 15 percent when the total is 200 or more. The fee is then accumulated line by line: for each line item, multiply its `unit_install_cents` by its `quantity`, apply the bundle discount by multiplying by one minus the chosen rate, and round that line's result half-up to whole cents; the install fee is the sum of those per-line rounded amounts. Each line is rounded before the lines are summed — rounding the running total instead is the wrong order and is not used. The result populates `install_fee_cents`.

**Storage fee.** The storage fee is a threshold charge over the units the contract has in storage — specifically the sum of `unit_count` across the contract's storage lots whose `status` is `STORED`; lots in `RESERVED` or `RELEASED` do not count. If the stored-unit total is 20 or fewer, the fee is a flat 15000 cents. If it exceeds 20, the fee is 15000 cents plus 600 cents for each stored unit beyond the first 20. The result populates `storage_fee_cents`.

**Early-bird discount and total.** The surcharge that enters the total is the contract's `custom_design_surcharge_cents`. The early-bird percentage is determined by contract type and timing: a `COMMERCIAL` contract earns 10 percent and an `HOA` contract earns 12 percent, but only when the logical clock at sign time is at or before the `early_bird_deadline`; an `EVENT` contract never qualifies, and signing after the deadline never qualifies, so in those cases the percentage is zero. The early-bird discount is that percentage applied to the sum of the install fee and the storage fee, rounded half-up to whole cents — the custom-design surcharge is never discounted. This figure populates `early_bird_discount_cents` (which is therefore 0 for an `EVENT` contract or any contract signed after its deadline). The contract total is then the install fee plus the storage fee plus the surcharge, minus the early-bird discount, and populates `total_amount_cents`.

### 3.4. Crews, Work Orders, and Routed Visits

Field operations run on crews. A field supervisor registers a `Crew` with a `crew_name`, a `daily_capacity_minutes` figure (at least 1) representing the minutes of route work the crew can absorb on a scheduled date, and a `home_base_zip` depot ZIP used for routing. A crew also carries two computed read-back figures, `planned_utilization_pct` and `actual_utilization_pct`, each starting at 0.

A field supervisor opens a `WorkOrder` against a contract by supplying its `contract_id` and a `job_type` of `INSTALL`, `REFRESH`, or `TAKEDOWN`. A work order carries two parallel status dimensions that evolve independently: a `schedule_status` ranging over `UNSCHEDULED`, `SCHEDULED`, `DISPATCHED`, `COMPLETED`, and `CANCELLED`, and a `billing_status` ranging over `PENDING`, `INVOICED`, and `PAID`. A new work order starts `UNSCHEDULED` and `PENDING`, with a null `crew_id`, a null `scheduled_date`, and a null `route_total_minutes`. Before scheduling, the supervisor lays out the route as an ordered set of `Visit` legs; each visit references its route through `work_order_id` and carries a 1-based `stop_sequence` (at least 1; ties in sequence are broken by `created_at` ascending), a `leg_distance_km` drive distance from the previous stop or from the depot for the first stop (zero or more), and a planned `on_site_minutes` (zero or more). A visit begins in `visit_status` `PLANNED` with a null `actual_minutes`, and may individually be completed — recording its `actual_minutes` and moving `PLANNED` to `COMPLETED` — or skipped, moving `PLANNED` to `SKIPPED`.

Scheduling advances the work order's `schedule_status` from `UNSCHEDULED` to `SCHEDULED`. The schedule call supplies the `crew_id` to assign and the `scheduled_date` to work. Scheduling is permitted only when the work order is `UNSCHEDULED`, the owning contract is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`, HTTP 409), the work order has at least one visit, and the crew clears the double-booking check described below. These checks fire in a fixed order: the `UNSCHEDULED` state guard first (`ERR_INVALID_STATE`), then the crew double-booking check (`ERR_CREW_DOUBLE_BOOKED`), then the contract-`ACTIVE` check (`ERR_CONTRACT_NOT_ACTIVE`), and finally the at-least-one-visit check, which when no visit exists is itself rejected with `ERR_INVALID_STATE` (HTTP 409). On success the system records the `crew_id` and `scheduled_date`, computes `route_total_minutes`, and recomputes the assigned crew's planned utilization. From `SCHEDULED` the supervisor dispatches the work order, moving it to `DISPATCHED` (permitted only from `SCHEDULED`), and from `DISPATCHED` completes it, moving it to `COMPLETED`. Completion requires the work order to be `DISPATCHED` and every visit on it to be in `COMPLETED` or `SKIPPED`; a still-`PLANNED` visit blocks completion with `ERR_VISITS_NOT_COMPLETE` (HTTP 409). Completion recomputes the crew's actual utilization. A work order may also be cancelled from either `UNSCHEDULED` or `SCHEDULED`, moving its `schedule_status` to `CANCELLED`; if it was `SCHEDULED`, cancellation frees the crew's date window and recomputes that crew's planned utilization. Every one of these transitions increments the work order's `version`.

**Route time.** Scheduling computes `route_total_minutes` from the work order's visits, taken in `stop_sequence` ascending order with ties broken by `created_at` ascending. Drive time is accumulated leg by leg: for each visit, divide its `leg_distance_km` by an average speed of 40 kilometers per hour and multiply by 60 to get drive minutes, then round that leg half-up to a whole minute; the drive total is the sum of those per-leg rounded minutes. Each leg is rounded before summing — summing raw minutes and rounding once at the end is the wrong order and is not used. On-site time is the plain sum of `on_site_minutes` across the visits. The route total is the drive total plus the on-site total.

**Crew double-booking.** A crew may not be scheduled onto a date that collides with another of its commitments. The requested `scheduled_date` must clear every other non-cancelled work-order window already on that crew by more than a one-day buffer — the comparison is a closed-interval, buffer-strict check, so a date whose absolute gap from an existing window is one day or less is a collision; the one-day boundary itself is inclusive, meaning a date falling exactly one day before or after an existing window is a collision. A violation is rejected with `ERR_CREW_DOUBLE_BOOKED` (HTTP 409).

**Crew utilization.** Both utilization figures are whole-number percentages, rounded half-up, and are not capped at 100. The planned figure looks at the crew's work orders in `schedule_status` `SCHEDULED` or `DISPATCHED`, finds the crew's busiest date — the `scheduled_date` carrying the greatest summed `route_total_minutes`, with ties broken by the earliest date — sums `route_total_minutes` for the work orders on that date, divides by the crew's `daily_capacity_minutes`, multiplies by 100, and rounds half-up to populate `planned_utilization_pct`. It is recomputed whenever a work order is scheduled and whenever a scheduled work order is cancelled. The actual figure looks only at completed work, summing the `actual_minutes` of visits in `COMPLETED` on the crew's `COMPLETED` work orders' busiest date, dividing by `daily_capacity_minutes`, multiplying by 100, and rounding half-up to populate `actual_utilization_pct`; it is recomputed on work-order completion.

### 3.5. Billing Completed Work

A work order's billing dimension moves independently of its schedule dimension. An account manager invoices a work order, advancing its `billing_status` from `PENDING` to `INVOICED`; invoicing requires the `billing_status` to be `PENDING` and the `schedule_status` to already be `COMPLETED`, and an attempt to invoice work that is not yet schedule-complete is rejected with `ERR_WORKORDER_NOT_COMPLETED` (HTTP 409). The account manager then marks the work order paid, advancing `INVOICED` to `PAID`, which requires only that `billing_status` be `INVOICED`. Each billing transition increments the work order's `version`.

### 3.6. Off-Season Storage

Off-season décor is held in warehouse bays. A field supervisor creates a `StorageBay` with a `bay_code` label (unique across all bays) and a `capacity_units` ceiling (at least 1) on how many décor units the bay can hold across overlapping lots; a colliding `bay_code` is rejected with `ERR_DUPLICATE_CODE` (HTTP 409).

A field supervisor reserves a `StorageLot` for a contract by supplying its `contract_id`, the `storage_bay_id` of the holding bay, a `unit_count` of stored décor units (at least 1), and a half-open occupancy interval delimited by `stored_from` (inclusive start) and `released_on` (exclusive end), where `released_on` must be strictly after `stored_from`. The reservation must not push the bay over its aggregate capacity: across the half-open interval from `stored_from` up to but not including `released_on`, the sum of `unit_count` over all lots whose intervals overlap, including the new lot, must not exceed the bay's `capacity_units`; a reservation that would exceed it is rejected with `ERR_BAY_CAPACITY_EXCEEDED` (HTTP 409). A new lot begins in `status` `RESERVED`. Storage lifecycle runs `RESERVED`, `STORED`, `RELEASED`, with `RELEASED` terminal.

A field supervisor checks a lot in, advancing `RESERVED` to `STORED`; check-in requires the lot to be `RESERVED` and the owning contract to be in `SIGNED` or `ACTIVE`; a check-in whose owning contract is in neither state is rejected with `ERR_INVALID_STATE` (HTTP 409). The set of `STORED` lots for a contract is exactly the input to the storage-fee computation at signing (§3.3). A supervisor releases a lot, advancing `STORED` to `RELEASED`, which requires the lot to be `STORED` and frees the bay capacity that lot's interval occupied. Contract cancellation also releases lots, as described in §3.1: every `RESERVED` or `STORED` lot for the cancelled contract is moved to `RELEASED`. Each storage-lot transition increments the lot's `version`.

### 3.7. Damage Discovery, Settlement, and Restock

Damage is found during takedown. A field supervisor opens a `DamageReport` against a work order by supplying the damaged SKU's `inventory_item_id` and a `damaged_qty` of assessed units (at least 1); the report references its work order through `work_order_id`. A new report starts in `status` `OPEN` with a null `resolution_path` and null `replacement_cost_cents` and `settlement_total_cents`. Reports move through `OPEN`, `ASSESSED`, `SETTLED`, and `VOID`, with `SETTLED` and `VOID` terminal. A supervisor may void an open report, moving `OPEN` to `VOID`, which requires only that the report be `OPEN`.

Assessing a report advances `OPEN` to `ASSESSED`. The assess call supplies the `resolution_path`, which is pinned at this moment to either `REPAIR` or `RESTOCK` and determines how settlement later cascades. Assessment is permitted only when the report is `OPEN` and the parent work order is a `TAKEDOWN` whose `schedule_status` is `COMPLETED`; if the parent work order is not a completed takedown, the request is rejected with `ERR_DAMAGE_CONTEXT_INVALID` (HTTP 409). Assessment computes the two money figures.

**Settlement amount.** The system first computes the replacement cost as `damaged_qty` multiplied by the inventory item's `unit_replacement_cents`, populating `replacement_cost_cents`. It then picks a base labor percentage from that replacement cost: 20 percent when the replacement cost is below 50000 cents; 15 percent when it is at least 50000 but below 150000 cents; and 10 percent when it is 150000 cents or more. A loyalty waiver may reduce this: if the owning contract is in `RENEWAL_OFFERED` or has a `RenewalOffer` in `SENT`, the effective percentage is the base percentage reduced by 5 percentage points but never below a 5 percent floor — that is, the larger of the base minus 5 points and 5 percent; otherwise the effective percentage is the base percentage unchanged. The labor fee is the replacement cost multiplied by the effective percentage, rounded half-up to whole cents. The settlement total is the replacement cost plus the labor fee, populating `settlement_total_cents`.

**Settling, and the two branches.** Settling advances `ASSESSED` to `SETTLED` and requires the report to be `ASSESSED`. The settle behavior forks on the `resolution_path` chosen at assessment, and the two branches receive deliberately different effects. On the `REPAIR` branch — permitted only when `resolution_path` is `REPAIR` — the units are repaired in place: there is no inventory movement, no storage-lot change, and no restock order; the settlement is simply recorded. On the `RESTOCK` branch — permitted only when `resolution_path` is `RESTOCK` — settling mints a new `RestockOrder` in `status` `REQUESTED` whose `damage_report_id` points back to this report and whose `quantity` equals the report's `damaged_qty`, and then decrements the referenced inventory item's `on_hand_qty` by `damaged_qty`, floored at 0 so stock never goes negative. Both branches increment the damage report's `version`; the `RESTOCK` branch additionally advances the new restock order and the affected inventory item.

A `RestockOrder` may also exist for a manual replenishment, in which case its `damage_report_id` is null. Either way it carries the `inventory_item_id` of the SKU to replenish and a `quantity` (at least 1), and starts in `status` `REQUESTED`. The platform operator fulfills it, advancing `REQUESTED` to `FULFILLED` (permitted only when `REQUESTED`); fulfillment increments the referenced inventory item's `on_hand_qty` by the restock order's `quantity` — compensating the settle-time decrement — and increments the restock order's `version`.

### 3.8. The Décor Catalog and Stock

The platform operator maintains the catalog of `InventoryItem` SKUs. Each is created with a `sku` code (unique across the catalog; a collision is rejected with `ERR_DUPLICATE_CODE`), a `category` of `TREE`, `WREATH`, `GARLAND`, or `LIGHTING`, a `unit_replacement_cents` replacement cost that drives damage settlement, and optionally an `on_hand_qty` warehouse stock count (default 0, never negative) and a `reorder_threshold` (default 0, never negative) at or below which the SKU is considered low-stock. The `on_hand_qty` is the figure the restock cascade decrements on a `RESTOCK` settlement and replenishes on restock fulfillment, as described in §3.7.

### 3.9. Renewal: Offer, Decision, and the Renewal Chain

When a season closes, an active contract can be offered for renewal. An account manager creates a `RenewalOffer` against an `ACTIVE` contract; this single action both mints the offer and moves the contract's `schedule_status`-independent lifecycle from `ACTIVE` to `RENEWAL_OFFERED`. Creation is permitted only when the contract is `ACTIVE` and no existing `RenewalOffer` for that contract is in `DRAFT` or `SENT`; if the contract is not `ACTIVE` or such an offer already exists, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). The create supplies the offer's `expires_at` instant (after which an unanswered offer lapses) and the OCC field `expected_contract_version`; because this write advances the contract's `version`, it carries the OCC guard of §2.7, and a create carrying a stale `expected_contract_version` is rejected with `ERR_STALE_CONTRACT_VERSION`. The offer is born in `status` `DRAFT`, references its contract through `contract_id`, and at creation has its `provisional_price_cents` computed (the provisional renewal quote) while `final_price_cents` stays null. The contract's `version` is incremented by this creation. Renewal offers move through `DRAFT`, `SENT`, `ACCEPTED`, `DECLINED`, and `EXPIRED`, with `ACCEPTED`, `DECLINED`, and `EXPIRED` terminal.

**Renewal pricing.** The renewal quote starts from the offered contract's `total_amount_cents`. An escalation applies for recurring types — 5 percent for a `COMMERCIAL` or `HOA` contract, and none for an `EVENT` contract — so the escalated base is the contract total multiplied by one plus the escalation rate, rounded half-up to whole cents. The provisional quote computed at offer creation is exactly this escalated base and excludes any damage carry-forward, populating `provisional_price_cents`. The final price, computed at acceptance, takes the same escalated base and adds the carry-forward of unsettled damage: the sum of `settlement_total_cents` over the contract's work orders' damage reports that are in `ASSESSED` — that is, assessed but not yet settled. This sum populates `final_price_cents` and equals the provisional figure precisely when no assessed-but-unsettled report exists.

**Sending and deciding.** An account manager sends a draft offer, advancing `DRAFT` to `SENT`; sending requires the offer to be `DRAFT` and its parent contract to be `RENEWAL_OFFERED`, and a send whose offer is not `DRAFT` or whose parent contract is not `RENEWAL_OFFERED` is rejected with `ERR_INVALID_STATE` (HTTP 409). The client's contact then decides a sent offer, and the three outcomes diverge sharply.

Accepting advances the offer `SENT` to `ACCEPTED` and is permitted only when the offer is `SENT` and the logical clock is at or before the offer's `expires_at`; an accept attempted after `expires_at` is rejected with `ERR_OFFER_EXPIRED` (HTTP 409). Acceptance is a depth-three cascade. First the offer is marked `ACCEPTED` and its `final_price_cents` is computed by the renewal-pricing rule above. Second, a brand-new `Contract` is minted in `status` `SIGNED`, with its `renewed_from_contract_id` set to the accepted offer's contract `id`, its `total_amount_cents` set to the offer's `final_price_cents`, and its `season_year` set to the old contract's `season_year` plus one; the minted contract copies the old contract's `client_id`, `contract_type`, `early_bird_deadline`, and `custom_design_surcharge_cents`, and leaves its other computed money fields (`install_fee_cents`, `storage_fee_cents`, `early_bird_discount_cents`) null. Third, the old contract's `status` is moved to `EXPIRED`, retiring it. The accepted offer's `version` advances, and the old contract's `version` advances as it expires.

Declining advances the offer `SENT` to `DECLINED` (permitted only when `SENT`) and reverts the parent contract from `RENEWAL_OFFERED` back to `ACTIVE`, so that another offer may be issued later — the renewal loop is cyclic. Expiry is the time-driven counterpart: once the logical clock passes the offer's `expires_at`, a sent offer may be expired, advancing `SENT` to `EXPIRED` and likewise reverting the parent contract from `RENEWAL_OFFERED` back to `ACTIVE`; expiry requires the offer to be `SENT` and the logical clock to be strictly past `expires_at`, and an expire attempt at or before `expires_at` is rejected with `ERR_INVALID_STATE` (HTTP 409). Both decline and expire increment the offer's `version` and the reverted contract's `version`. The self-referential `renewed_from_contract_id` set at acceptance chains the renewal generations together, and contracts can be filtered by that field to walk a renewal chain.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including every state transition and every billing or settlement action — return `200 OK`. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Create a commercial/HOA/event account | AccountManager |
| GET | `/clients/{id}` | Fetch a client account | AccountManager, FieldSupervisor, ClientContact, PlatformAdmin |
| GET | `/clients` | List clients (filter by `account_type`) | AccountManager, PlatformAdmin |
| POST | `/clients/{id}/contracts` | Create a DRAFT contract for the client | AccountManager |
| GET | `/clients/{id}/contracts` | List a client's contracts | AccountManager, FieldSupervisor, ClientContact, PlatformAdmin |
| GET | `/contracts/{id}` | Fetch a contract with computed fee fields | AccountManager, FieldSupervisor, ClientContact, PlatformAdmin |
| GET | `/contracts` | List/filter contracts (by `status`, `renewed_from_contract_id`) | AccountManager, PlatformAdmin |
| POST | `/clients/{id}/contracts/{contract_id}/propose` | Move a contract DRAFT → PROPOSED | AccountManager |
| POST | `/clients/{id}/contracts/{contract_id}/sign` | Move a contract PROPOSED → SIGNED; compute fees | ClientContact |
| POST | `/clients/{id}/contracts/{contract_id}/activate` | Move a contract SIGNED → ACTIVE | AccountManager |
| POST | `/clients/{id}/contracts/{contract_id}/cancel` | Move a contract ACTIVE → CANCELLED; cascade | AccountManager |
| POST | `/contracts/{id}/design-proposals` | Create a DRAFT proposal under a contract | AccountManager |
| GET | `/contracts/{id}/design-proposals` | List a contract's proposals (filter by `status`) | AccountManager, FieldSupervisor, ClientContact, PlatformAdmin |
| GET | `/design-proposals/{id}` | Fetch a proposal | AccountManager, FieldSupervisor, ClientContact, PlatformAdmin |
| POST | `/design-proposals/{id}/line-items` | Add a line item to a proposal | AccountManager |
| GET | `/design-proposals/{id}/line-items` | List a proposal's line items | AccountManager, FieldSupervisor, ClientContact, PlatformAdmin |
| POST | `/design-proposals/{id}/submit` | Move a proposal DRAFT → SUBMITTED | AccountManager |
| POST | `/design-proposals/{id}/accept` | Move a proposal SUBMITTED → ACCEPTED; supersede siblings; OCC-guarded | ClientContact |
| POST | `/design-proposals/{id}/reject` | Move a proposal SUBMITTED → REJECTED | ClientContact |
| POST | `/inventory-items` | Create a catalog décor SKU | PlatformAdmin |
| GET | `/inventory-items/{id}` | Fetch an inventory item | AccountManager, FieldSupervisor, PlatformAdmin |
| GET | `/inventory-items` | List catalog items (filter by `category`) | AccountManager, FieldSupervisor, PlatformAdmin |
| GET | `/inventory-items/{id}/proposal-line-items` | List line items referencing this SKU | AccountManager, FieldSupervisor, PlatformAdmin |
| POST | `/crews` | Create an installer crew | FieldSupervisor |
| GET | `/crews/{id}` | Fetch a crew with utilization fields | AccountManager, FieldSupervisor, PlatformAdmin |
| GET | `/crews` | List crews | AccountManager, FieldSupervisor, PlatformAdmin |
| POST | `/work-orders` | Create an UNSCHEDULED work order for a contract | FieldSupervisor |
| GET | `/work-orders/{id}` | Fetch a work order | AccountManager, FieldSupervisor, PlatformAdmin |
| GET | `/work-orders` | List/filter work orders (by `contract_id`, `crew_id`, `schedule_status`) | AccountManager, FieldSupervisor, PlatformAdmin |
| POST | `/work-orders/{id}/visits` | Add a route visit (leg) to a work order | FieldSupervisor |
| GET | `/work-orders/{id}/visits` | List a work order's visits | AccountManager, FieldSupervisor, PlatformAdmin |
| POST | `/work-orders/{id}/schedule` | Move a work order UNSCHEDULED → SCHEDULED; assign crew/date | FieldSupervisor |
| POST | `/work-orders/{id}/dispatch` | Move a work order SCHEDULED → DISPATCHED | FieldSupervisor |
| POST | `/work-orders/{id}/complete` | Move a work order DISPATCHED → COMPLETED | FieldSupervisor |
| POST | `/work-orders/{id}/cancel` | Move a work order UNSCHEDULED/SCHEDULED → CANCELLED | FieldSupervisor |
| POST | `/work-orders/{id}/invoice` | Move billing PENDING → INVOICED | AccountManager |
| POST | `/work-orders/{id}/mark-paid` | Move billing INVOICED → PAID | AccountManager |
| POST | `/visits/{id}/complete` | Move a visit PLANNED → COMPLETED; record actual minutes | FieldSupervisor |
| POST | `/visits/{id}/skip` | Move a visit PLANNED → SKIPPED | FieldSupervisor |
| GET | `/visits/{id}` | Fetch one visit | AccountManager, FieldSupervisor, PlatformAdmin |
| POST | `/storage-bays` | Create a warehouse storage bay | FieldSupervisor |
| GET | `/storage-bays/{id}` | Fetch a storage bay | FieldSupervisor, AccountManager, PlatformAdmin |
| POST | `/storage-lots` | Reserve a storage lot for a contract on a bay | FieldSupervisor |
| GET | `/storage-lots/{id}` | Fetch a storage lot | FieldSupervisor, AccountManager, PlatformAdmin |
| GET | `/storage-lots` | List/filter storage lots (by `contract_id`, `storage_bay_id`, `status`) | FieldSupervisor, AccountManager, PlatformAdmin |
| POST | `/storage-lots/{id}/check-in` | Move a storage lot RESERVED → STORED | FieldSupervisor |
| POST | `/storage-lots/{id}/release` | Move a storage lot STORED → RELEASED; free bay capacity | FieldSupervisor |
| POST | `/work-orders/{id}/damage-reports` | Open a damage report against a TAKEDOWN work order | FieldSupervisor |
| GET | `/work-orders/{id}/damage-reports` | List a work order's damage reports | AccountManager, FieldSupervisor, PlatformAdmin |
| GET | `/damage-reports/{id}` | Fetch a damage report with settlement fields | AccountManager, FieldSupervisor, PlatformAdmin |
| GET | `/damage-reports` | List/filter damage reports (by `inventory_item_id`, `status`) | AccountManager, FieldSupervisor, PlatformAdmin |
| POST | `/damage-reports/{id}/assess` | Move a damage report OPEN → ASSESSED; pin path; compute settlement | FieldSupervisor |
| POST | `/damage-reports/{id}/settle` | Move a damage report ASSESSED → SETTLED; RESTOCK branch cascades | FieldSupervisor |
| POST | `/damage-reports/{id}/void` | Move a damage report OPEN → VOID | FieldSupervisor |
| GET | `/restock-orders/{id}` | Fetch a restock order | FieldSupervisor, PlatformAdmin |
| GET | `/restock-orders` | List/filter restock orders (by `damage_report_id`, `inventory_item_id`, `status`) | FieldSupervisor, PlatformAdmin |
| POST | `/restock-orders/{id}/fulfill` | Move a restock order REQUESTED → FULFILLED; replenish stock | PlatformAdmin |
| POST | `/contracts/{id}/renewal-offers` | Move a contract ACTIVE → RENEWAL_OFFERED; create DRAFT offer; OCC-guarded | AccountManager |
| GET | `/contracts/{id}/renewal-offers` | List a contract's renewal offers (filter by `status`) | AccountManager, ClientContact, PlatformAdmin |
| GET | `/renewal-offers/{id}` | Fetch a renewal offer | AccountManager, ClientContact, PlatformAdmin |
| POST | `/renewal-offers/{id}/send` | Move a renewal offer DRAFT → SENT | AccountManager |
| POST | `/renewal-offers/{id}/accept` | Move a renewal offer SENT → ACCEPTED; mint new contract; expire old | ClientContact |
| POST | `/renewal-offers/{id}/decline` | Move a renewal offer SENT → DECLINED; revert contract to ACTIVE | ClientContact |
| POST | `/renewal-offers/{id}/expire` | Move a renewal offer SENT → EXPIRED; revert contract to ACTIVE | AccountManager, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONTRACT_TYPE_MISMATCH` | 422 |
| `ERR_PROPOSAL_ALREADY_DECIDED` | 409 |
| `ERR_DAMAGE_CONTEXT_INVALID` | 409 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_BAY_CAPACITY_EXCEEDED` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_VISITS_NOT_COMPLETE` | 409 |
| `ERR_WORKORDER_NOT_COMPLETED` | 409 |
